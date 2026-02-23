import pandas as pd
import os
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)

class CSVDataProvider:
    def __init__(self, downloads_path):
        self.downloads_path = downloads_path
        self.index_data = None
        self.ce_data = None
        self.pe_data = None
        self._load_data()

    def _load_data(self):
        # We'll try to load the 2026 files preferentially
        index_file = os.path.join(self.downloads_path, "nifty50_3months.csv")
        ce_file = os.path.join(self.downloads_path, "OPTIDX_NIFTY_CE_22-Jan-2026_TO_22-Feb-2026.csv")
        pe_file = os.path.join(self.downloads_path, "OPTIDX_NIFTY_PE_22-Jan-2026_TO_22-Feb-2026.csv")

        if os.path.exists(index_file):
            logger.info(f"Loading index data from {index_file}")
            self.index_data = pd.read_csv(index_file, skipinitialspace=True, quotechar='"')
            self.index_data['Date'] = pd.to_datetime(self.index_data['Date'])
            self.index_data.set_index('Date', inplace=True)
            self.index_data.sort_index(inplace=True)
        else:
            logger.warning(f"Index file not found: {index_file}")

        if os.path.exists(ce_file):
            logger.info(f"Loading CE options data from {ce_file}")
            self.ce_data = pd.read_csv(ce_file, skipinitialspace=True)
            self.ce_data.columns = self.ce_data.columns.str.strip()
            self.ce_data['Date'] = pd.to_datetime(self.ce_data['Date'])
            # Expiry is in 25-Jun-2030 format
            self.ce_data['Expiry'] = pd.to_datetime(self.ce_data['Expiry'])
            
            # If index_data is missing recent dates, supplement from CE data
            if self.index_data is not None:
                latest_index_date = self.index_data.index.max()
                recent_ce = self.ce_data[self.ce_data['Date'] > latest_index_date]
                if not recent_ce.empty:
                    # Group by Date and take unique Underlying Value
                    supplement = recent_ce.groupby('Date')['Underlying Value'].first().to_frame()
                    supplement.columns = ['Close'] # Map Underlying Value to Close
                    # Add dummy OHLC for consistency
                    supplement['Open'] = supplement['Close']
                    supplement['High'] = supplement['Close']
                    supplement['Low'] = supplement['Close']
                    self.index_data = pd.concat([self.index_data, supplement])
                    self.index_data.sort_index(inplace=True)
        else:
            logger.warning(f"CE options file not found: {ce_file}")

        if os.path.exists(pe_file):
            logger.info(f"Loading PE options data from {pe_file}")
            self.pe_data = pd.read_csv(pe_file, skipinitialspace=True)
            self.pe_data.columns = self.pe_data.columns.str.strip()
            self.pe_data['Date'] = pd.to_datetime(self.pe_data['Date'])
            self.pe_data['Expiry'] = pd.to_datetime(self.pe_data['Expiry'])
        else:
            logger.warning(f"PE options file not found: {pe_file}")

    def get_index_price(self, timestamp):
        if self.index_data is None:
            return None
        
        date = timestamp.date()
        try:
            row = self.index_data.loc[pd.Timestamp(date)]
            return row['Close']
        except KeyError:
            idx = self.index_data.index.get_indexer([pd.Timestamp(date)], method='ffill')[0]
            if idx != -1:
                return self.index_data.iloc[idx]['Close']
            return None

    def get_option_chain(self, timestamp):
        if self.ce_data is None or self.pe_data is None:
            return None
        
        date = pd.Timestamp(timestamp.date())
        ce_subset = self.ce_data[self.ce_data['Date'] == date]
        pe_subset = self.pe_data[self.pe_data['Date'] == date]
        
        if ce_subset.empty and pe_subset.empty:
            # Fallback to last available day
            last_date = self.ce_data[self.ce_data['Date'] <= date]['Date'].max()
            if pd.isna(last_date):
                print(f"DEBUG: No chain data for {date}")
                return None
            ce_subset = self.ce_data[self.ce_data['Date'] == last_date]
            pe_subset = self.pe_data[self.pe_data['Date'] == last_date]
            print(f"DEBUG: Using fallback date {last_date} for {date}")

        # Near-month expiry filtering
        near_expiry = ce_subset['Expiry'].min()
        ce_chain = ce_subset[ce_subset['Expiry'] == near_expiry].copy()
        pe_chain = pe_subset[pe_subset['Expiry'] == near_expiry].copy()
        
        if ce_chain.empty:
            print(f"DEBUG: No CE chain for expiry {near_expiry} on {date}")

        # Add synthetic symbols NIFTY24FEB24000CE
        def synth_symbol(row):
            exp = row['Expiry']
            month_str = exp.strftime('%b').upper()
            year_str = exp.strftime('%y')
            return f"NIFTY{year_str}{month_str}{int(row['Strike Price'])}{row['Option type']}"

        ce_chain['synth_symbol'] = ce_chain.apply(synth_symbol, axis=1)
        pe_chain['synth_symbol'] = pe_chain.apply(synth_symbol, axis=1)

        return {
            'CE': ce_chain,
            'PE': pe_chain,
            'date': ce_chain['Date'].iloc[0] if not ce_chain.empty else date,
            'expiry': near_expiry
        }

    def get_option_price(self, symbol, timestamp):
        # Extract components from synthetic symbol NIFTY26FEB25500CE
        match = re.match(r"NIFTY(\d{2})([A-Z]{3})(\d+)(CE|PE)", symbol)
        if not match:
            return 0.0
        
        year_str, month_str, strike_str, type_str = match.groups()
        strike = float(strike_str)
        
        data = self.ce_data if type_str == "CE" else self.pe_data
        if data is None: return 0.0
        
        date = pd.Timestamp(timestamp.date())
        # Filter for date and strike
        subset = data[(data['Date'] == date) & (data['Strike Price'] == strike)]
        
        if subset.empty:
            # Fallback to last available day
            last_dt = data[data['Date'] <= date]['Date'].max()
            if pd.isna(last_dt): return 0.0
            subset = data[(data['Date'] == last_dt) & (data['Strike Price'] == strike)]
            
        if not subset.empty:
            # Check for LTP or Close
            val = subset.iloc[0]['LTP']
            if val == "-" or pd.isna(val) or val == 0:
                val = subset.iloc[0]['Close']
            
            try:
                price = float(val) if val != "-" else 0.0
                if price == 0:
                     print(f"DEBUG: Price for {symbol} on {timestamp} is 0.0")
                return price
            except:
                return 0.0
        
        print(f"DEBUG: No price data found for {symbol} on {timestamp}")
        return 0.0
