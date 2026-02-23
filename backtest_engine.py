import os
import argparse
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any
import re
import json
import logging

from brokers import BrokerGateway, OrderRequest, Exchange, OrderType, TransactionType, ProductType
from strategy.survivor import SurvivorStrategy
from orders import OrderTracker
from logger import logger

class BacktestEngine:
    def __init__(self, strategy_class, config: Dict[str, Any], initial_capital: float = 100000.0, max_trades_per_day: int = 5):
        self.strategy_class = strategy_class
        self.config = config
        self.initial_capital = initial_capital
        self.max_trades_per_day = max_trades_per_day
        
        # Initialize Backtest Broker
        self.broker = BrokerGateway.from_name("backtest")
        self.driver = self.broker.driver
        self.driver.initial_capital = initial_capital
        self.driver.current_cash = initial_capital
        
        # Initialize Tracker
        self.order_tracker = OrderTracker()
        
        # Strategy instance
        self.strategy = None
        self.trades = []
        self.daily_trade_count = {}

    def fetch_historical_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch historical data using Zerodha driver (requires authentication).
        """
        logger.info(f"Fetching historical data for {symbol} from {start_date} to {end_date}")
        
        # Temporary switch to Zerodha to fetch data
        try:
            real_broker = BrokerGateway.from_name("zerodha")
            data = real_broker.get_history(symbol, "1m", start_date, end_date)
            if not data:
                logger.error("No historical data fetched. Please check broker credentials in .env")
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['ts'], unit='s')
            return df
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return pd.DataFrame()

    def load_csv_data(self, downloads_path: str) -> pd.DataFrame:
        """
        Load historical data from local CSV files.
        """
        from brokers.integrations.backtest.csv_provider import CSVDataProvider
        self.csv_provider = CSVDataProvider(downloads_path)
        self.driver.set_csv_provider(self.csv_provider)
        
        if self.csv_provider.index_data is not None:
             return self.csv_provider.index_data
        
        logger.error("Failed to load index data from CSV.")
        return pd.DataFrame()

    def run(self, data_df: pd.DataFrame):
        if data_df.empty:
            logger.error("Cannot run backtest with empty data.")
            return
        
        # Set instruments for the driver (needed for margin calculations etc if any)
        # For simplicity, we'll mock it if not present
        if self.driver.instruments_df is None:
            # Create a minimal instruments DF for the strategy
            mock_inst = pd.DataFrame([{
                'symbol': self.config['symbol_initials'] + '20000CE',
                'strike': 20000,
                'lot_size': 50,
                'instrument_type': 'CE',
                'segment': 'NFO-OPT'
            }])
            self.driver.set_instruments(mock_inst)

        # Prepare initial price if possible
        if not data_df.empty:
            first_row = data_df.iloc[0]
            initial_time = first_row['timestamp'] if 'timestamp' in first_row else data_df.index[0]
            initial_price = first_row['close'] if 'close' in first_row else first_row['Close']
            self.driver.set_current_time(initial_time)
            self.driver.set_price(self.config['index_symbol'], initial_price)
            if self.csv_provider:
                self.driver.download_instruments()

        # Initialize strategy
        self.strategy = self.strategy_class(self.broker, self.config, self.order_tracker)
        
        logger.info(f"Starting backtest loop with {len(data_df)} days/ticks...")
        
        skip_first_day = True
        
        for idx, row in data_df.iterrows():
            # Handle both Zerodha style ('timestamp', 'close') and CSV style ('Date', 'Close')
            current_time = row['timestamp'] if 'timestamp' in row else row.name
            
            # Update driver state only once for instrument download etc
            self.driver.set_current_time(current_time)
            
            # Handle Rolling Expiry for CSV
            if self.csv_provider:
                chain = self.driver.get_option_chain("NIFTY", current_time)
                if chain and not chain['CE'].empty:
                    first_synth = chain['CE'].iloc[0]['synth_symbol']
                    match = re.match(r"(NIFTY\d{2}[A-Z]{3})", first_synth)
                    if match:
                        new_prefix = match.group(1)
                        if new_prefix != self.strategy.symbol_initials:
                            logger.info(f"Rolling contract prefix: {self.strategy.symbol_initials} -> {new_prefix}")
                            self.strategy.symbol_initials = new_prefix
                            self.strategy.refresh_instruments()
                
                self.driver.download_instruments()
            
            if skip_first_day:
                # Use first day only for setting price and initial state
                day_price = row['Close'] if 'Close' in row else row['close']
                self.driver.set_price(self.config['index_symbol'], day_price)
                skip_first_day = False
                logger.info(f"Initialized metrics on {current_time} (Price: {day_price}). Trading starts next tick.")
                continue

            # Simulated ticks: Open, High, Low, Close
            prices = [row['Open'], row['High'], row['Low'], row['Close']] if 'Open' in row else [row['close']]
            
            for price in prices:
                self.driver.set_price(self.config['index_symbol'], price)
                
                # Update P&L for all open positions by refreshing their prices
                open_symbols = list(self.driver.positions.keys())
                for symbol in open_symbols:
                    if symbol != self.config['index_symbol']:
                        quote = self.driver.get_quote(symbol)
                        if quote and quote.last_price:
                            self.driver.set_price(symbol, quote.last_price)
                
                # Trade limit check
                date_str = current_time.date().isoformat()
                trades_today = self.daily_trade_count.get(date_str, 0)
                
                # Simulate Tick Update
                tick = {'last_price': price, 'ltp': price, 'timestamp': current_time}
                
                # Capture trades made during this step
                pre_trade_count = len(self.driver.trades)
                
                if trades_today < self.max_trades_per_day:
                    self.strategy.on_ticks_update(tick)
                
                post_trade_count = len(self.driver.trades)
                if post_trade_count > pre_trade_count:
                    new_trades = post_trade_count - pre_trade_count
                    self.daily_trade_count[date_str] = trades_today + new_trades
                    logger.info(f"Executed {new_trades} trades at {current_time} - Price: {price}")

        self.results = self.calculate_metrics()
        self.save_results()

    def calculate_metrics(self) -> Dict[str, Any]:
        funds = self.driver.get_funds()
        total_pnl = funds.equity - self.initial_capital
        total_trades = len(self.driver.trades)
        
        return {
            "initial_capital": self.initial_capital,
            "final_equity": funds.equity,
            "total_pnl": total_pnl,
            "total_pnl_percent": (total_pnl / self.initial_capital) * 100,
            "total_trades": total_trades,
            "trades": self.driver.trades
        }

    def save_results(self):
        output_dir = "backtest_results"
        os.makedirs(output_dir, exist_ok=True)
        
        with open(os.path.join(output_dir, "results.json"), "w") as f:
            json.dump(self.results, f, indent=4, default=str)
        
        logger.info(f"Backtest results saved to {output_dir}/results.json")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Survivor Strategy Backtester")
    parser.add_argument("--start", type=str, required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument("--max-trades", type=int, default=5)
    parser.add_argument("--use-csv", action="store_true", help="Use local CSV files instead of Zerodha")
    parser.add_argument("--csv-path", type=str, default=r"C:\Users\Rahul Sharma\Documents\Downloads", help="Path to CSV files")
    
    parser.add_argument("--force-trades", action="store_true", help="Force trades by reducing gaps to 1")
    
    args = parser.parse_args()
    
    # Load strategy configuration
    config_file = "strategy/configs/survivor.yml"
    import yaml
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)['default']
    
    # Realistic account sizing for ₹1 Lakh capital
    config['pe_quantity'] = 25  # Force small lot size
    config['ce_quantity'] = 25
    config['sell_multiplier_threshold'] = 5  # Allow some scaling but keep it sane
    
    # If using CSV, we might need slightly larger gaps than 1 to avoid excessive multiplier triggers
    if args.force_trades:
        config['pe_gap'] = 1
        config['ce_gap'] = 1
        logger.info("Forcing trades - setting gaps to 1")
    else:
        # Default manageable gaps for daily data
        config['pe_gap'] = 50 
        config['ce_gap'] = 50
    
    engine = BacktestEngine(SurvivorStrategy, config, initial_capital=args.capital, max_trades_per_day=args.max_trades)
    
    # Fetch data
    if args.use_csv:
        data = engine.load_csv_data(args.csv_path)
        # Filter by start and end dates
        start_ts = pd.to_datetime(args.start)
        end_ts = pd.to_datetime(args.end)
        data = data[(data.index >= start_ts) & (data.index <= end_ts)]
        
        # Determine symbol_initials from first available chain
        if not data.empty:
            first_date = data.index[0]
            chain = engine.csv_provider.get_option_chain(first_date)
            if chain and not chain['CE'].empty:
                synth = chain['CE'].iloc[0]['synth_symbol']
                # synth is like NIFTY26FEB25500CE
                # Strategy wants prefix NIFTY26FEB
                match = re.match(r"(NIFTY\d{2}[A-Z]{3})", synth)
                if match:
                    config['symbol_initials'] = match.group(1)
                    logger.info(f"Detected CSV symbol prefix: {config['symbol_initials']}")
    else:
        data = engine.fetch_historical_data(config['index_symbol'], args.start, args.end)
    
    if not data.empty:
        engine.run(data)
        print("\nBacktest Summary:")
        print(f"Final Equity: {engine.results['final_equity']:.2f}")
        print(f"Total P&L: {engine.results['total_pnl']:.2f} ({engine.results['total_pnl_percent']:.2f}%)")
        print(f"Total Trades: {engine.results['total_trades']}")
    else:
        print("Data source is empty. Cannot run backtest.")
