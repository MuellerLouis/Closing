from time import time
import os
import copy

from tqdm import tqdm
import pandas as pd
import numpy as np
from collections import deque


class Research:
	def __init__(self, file):
		t0 = time()
		self._snapbook = pd.read_csv(file, header=0)
		self._snapbook.rename(columns={'start_close_vol_bid': 'SS_0_vol_bid', 'start_close_vol_ask': 'SS_0_vol_ask'}, inplace=True)
		self._symbols = self._snapbook['symbol'].unique()
		self._dates = self._snapbook['onbook_date'].unique()
		self._snapbook.set_index(['onbook_date', 'symbol', 'price'], drop=True, inplace=True)
		self._snapbook.sort_index(inplace=True)
		self._snapbook.replace({np.nan: 0}, inplace=True)
		
		self._result_dict = {}  # Collects all the results
		
		print(">>> Super-Class initiated ({} seconds)".format(round(time() - t0, 2)))
	
	@property
	def snapshots(self):
		return self._snapbook
	
	@staticmethod
	def _extract_market_orders(imp_df: pd.DataFrame) -> tuple:
		"""
		Removes market orders from an order book snapshot.
		:param imp_df: Pandas DataFrame
		:return: Pandas DataFrame without the market orders
		"""
		try:
			mark_buy = imp_df.loc[0, 'bids']
		except KeyError:
			imp_df.loc[0, :] = 0
			mark_buy = imp_df.loc[0, 'bids']
		
		try:
			mark_sell = imp_df.loc[0, 'asks']
		except KeyError:
			imp_df.loc[0, :] = 0
			mark_sell = imp_df.loc[0, 'asks']
		
		df = imp_df.drop(0, axis=0).sort_index()
		
		return df, mark_buy, mark_sell
	
	@staticmethod
	def _calc_uncross(bids: pd.Series, asks: pd.Series) -> dict:
		"""
		Function calculates the theoretical uncross price of a closing order book.
		:return: dict() with price/trade_vol/cum_bids/cum_asks/total_bids/total_asks
		"""
		base_df = pd.DataFrame({'bids': bids, 'asks': asks})
		df, mark_buy, mark_sell = Research._extract_market_orders(base_df)
		
		if 0 in df[['asks', 'bids']].sum().values:  # Where one side is empty
			return dict(price=np.nan, trade_vol=np.nan, cum_bids=np.nan, cum_asks=np.nan,
			            total_bids=np.nan, total_asks=np.nan)
		
		else:
			n_lim = df.shape[0]
			limit_bids, limit_asks = deque(df['bids'], n_lim), deque(df['asks'], n_lim)
			
			neg_bids = limit_bids.copy()
			neg_bids.appendleft(0)
			
			cum_bids = mark_buy + sum(limit_bids) - np.cumsum(neg_bids)
			cum_asks = mark_sell + np.cumsum(limit_asks)
			
			imbalances = cum_bids - cum_asks
			i = np.argmin(abs(imbalances))
			trade_vol = min(cum_bids[i], cum_asks[i])
			sum_bids, sum_asks = max(cum_bids), max(cum_asks)
			
			if min(cum_bids[i], cum_asks[i]) == 0:
				output = dict(price=np.nan, trade_vol=np.nan, cum_bids=np.nan, cum_asks=np.nan,
				              total_bids=sum_bids, total_asks=sum_asks)
			else:
				output = dict(price=df.index[i], trade_vol=trade_vol, cum_bids=cum_bids[i], cum_asks=cum_asks[i],
				              total_bids=sum_bids, total_asks=sum_asks)
			
			return output
	
	@staticmethod
	def _calc_preclose(bids: pd.Series, asks: pd.Series) -> dict:
		"""
		This helper function calculates the hypothetical last midquote before closing auctions start.
		This method takes only inputs from the self._remove_liq method.
		"""
		base_df = pd.DataFrame({'bids': bids, 'asks': asks})
		try:
			base_df.drop(index=[0], inplace=True)
		except KeyError:
			pass
		
		n_lim = base_df.shape[0]
		limit_bids, limit_asks = deque(base_df['bids'], n_lim), deque(base_df['asks'], n_lim)
		neg_asks = limit_asks.copy()
		neg_asks.appendleft(0)
		
		cum_bids = np.cumsum(limit_bids)
		cum_asks = sum(limit_asks) - np.cumsum(neg_asks)
		
		total = cum_bids + cum_asks
		
		i_top_bid = np.argmax(total)
		i_top_ask = len(total) - np.argmax(np.flip(total)) - 1
		maxbid, minask = base_df['bids'].index[i_top_bid], base_df['asks'].index[i_top_ask]
		
		if i_top_bid > i_top_ask:
			raise ValueError("i_top_bid not smaller than i_top_ask (spread overlap)")
		
		else:
			output = dict(abs_spread=round(minask - maxbid, 4), midquote=round((maxbid + minask) / 2, 4),
			              rel_spread=round((minask - maxbid) / ((maxbid + minask) / 2) * 10 ** 4, 4))
			return output
	
	def export_results(self, filename, filetype) -> None:
		df = self.results_to_df()
		if filetype == 'xlsx':
			df.round(4).to_excel(os.getcwd() + "\\Exports\\{}.xlsx".format(filename))
		elif filetype == 'csv':
			df.round(4).to_csv(os.getcwd() + "\\Exports\\{}.csv".format(filename))


class SensitivityAnalysis(Research):
	def __init__(self, file, base, perc):
		super().__init__(file)
		if base in {'SeparatePassive', 'SeparateOrders', 'FullPassive', 'FullLiquidity', 'CrossedVolume'}:
			self._base = base
		else:
			raise KeyError("base not in {'SeparatePassive',''SeparateOrders'','FullPassive','FullLiquidity','CrossedVolume'}")
		
		self._mode_dict = dict(
			bid_limit=('bid', None, perc), ask_limit=('ask', None, perc), all_limit=('both', None, perc),
			bid_market=('bid', 'all', [1]), ask_market=('ask', 'all', [1]), all_market=('both', 'all', [1]),
			bid_cont=('bid', 'cont', [1]), ask_cont=('ask', 'cont', [1]), all_cont=('both', 'cont', [1])
		)
	
	def _remove_orders(self, date, title, perc=0, side=None, market=None) -> dict:
		"""
		This function removes a certain percentage of liquidity from the closing auction.
		It is called for a every date-title combination individually
		:param date: Onbook_date
		:param title: Name of the stock
		:param perc: Values in decimals, i.e. 5% is handed in as 0.05
		:param side: ['bid','ask','all']. Which side should be included in the removal
		:param market: True if market orders are included and False otherwise
		:return: A dateframe with new bid-ask book based on removing adjustments.
		"""
		imp_df = self._snapbook.loc[(date, title), :]
		
		if perc == 0:
			return dict(asks=imp_df['end_close_vol_ask'], bids=imp_df['end_close_vol_bid'])
		
		# Removal of Market Orders
		if market == "all":  # Removes all market orders in closing auction
			ret_df = imp_df.loc[:, ('end_close_vol_ask', 'end_close_vol_bid')]
			try:
				if side in ['bid', 'both']:
					ret_df.loc[0, 'end_close_vol_bid'] = 0
				if side in ['ask', 'both']:
					ret_df.loc[0, 'end_close_vol_ask'] = 0
				return dict(asks=ret_df['end_close_vol_ask'], bids=ret_df['end_close_vol_bid'])
			
			except KeyError:
				return dict(asks=ret_df['end_close_vol_ask'], bids=ret_df['end_close_vol_bid'])
		
		elif market == 'cont':
			ret_df = imp_df.loc[:, ('end_close_vol_ask', 'end_close_vol_bid')]
			try:
				if side in ['bid', 'both']:
					ret_df.loc[0, 'end_close_vol_bid'] -= imp_df.loc[0, 'SS_0_vol_bid']
				if side in ['ask', 'both']:
					ret_df.loc[0, 'end_close_vol_ask'] -= imp_df.loc[0, 'SS_0_vol_ask']
				ret_df[ret_df < 0] = 0
				return dict(asks=ret_df['end_close_vol_ask'], bids=ret_df['end_close_vol_bid'])
			
			except KeyError:
				return dict(asks=ret_df['end_close_vol_ask'], bids=ret_df['end_close_vol_bid'])
		
		else:
			bids = imp_df['end_close_vol_bid'].tolist()
			asks = imp_df['end_close_vol_ask'].tolist()
			
			if self._base == 'SeparatePassive':  # Only considering limit orders for adjustments
				rem_bid = sum(bids[1:]) * perc
				rem_ask = sum(asks[1:]) * perc
			elif self._base == 'SeparateOrders':
				rem_bid = sum(bids) * perc
				rem_ask = sum(asks) * perc
			elif self._base == 'FullPassive':
				rem_bid = sum(bids[1:]) + sum(asks[1:]) * perc / 2
				rem_ask = sum(bids[1:]) + sum(asks[1:]) * perc / 2
			elif self._base == 'FullLiquidity':
				rem_bid = min((sum(bids) + sum(asks)) * perc / 2, sum(bids))
				rem_ask = min((sum(bids) + sum(asks)) * perc / 2, sum(asks))
			elif self._base == 'CrossedVolume':
				close_volume = self._calc_uncross(bids=imp_df['end_close_vol_bid'], asks=imp_df['end_close_vol_ask'])['trade_vol']
				rem_bid = close_volume * perc
				rem_ask = close_volume * perc
			else:
				raise KeyError("base not in {'SeparatePassive',''SeparateOrders'','FullPassive','FullLiquidity','CrossedVolume'}")
			
			if side in ['bid', 'both']:
				b = len(bids) - 1
				while rem_bid > 0:
					if bids[0] != 0:
						local_vol = bids[0]
						bids[0] = local_vol - min(local_vol, rem_bid)
						rem_bid -= min(rem_bid, local_vol)
					else:
						local_vol = bids[b]
						bids[b] = local_vol - min(local_vol, rem_bid)
						rem_bid -= min(rem_bid, local_vol)
						b -= 1
			
			if side in ['ask', 'both']:
				a = 1
				while rem_ask > 0:
					if asks[0] != 0:
						local_vol = asks[0]
						asks[0] = local_vol - min(local_vol, rem_ask)
						rem_ask -= min(rem_ask, local_vol)
					else:
						local_vol = asks[a]
						asks[a] = local_vol - min(local_vol, rem_ask)
						rem_ask -= min(rem_ask, local_vol)
						a += 1
			
			ret_df = pd.DataFrame([asks, bids], index=['end_close_vol_ask', 'end_close_vol_bid'], columns=imp_df.index).T
			return dict(asks=ret_df['end_close_vol_ask'], bids=ret_df['end_close_vol_bid'])
	
	def process(self) -> None:
		"""
		This function is supposed to exeucte the required calculations and add it to an appropriate data format.
		It calls other helper functions in order to determine the results of the analysis.
		"""
		dump = {}
		
		# for key in iter(self._mode_dict.keys()):
		for key in {'bid_market', 'ask_market', 'all_market','bid_cont','ask_cont','all_cont'}:
			side, mkt, percents = self._mode_dict[key]
			dump[key] = {}
			
			for date in tqdm(self._dates):
				current_symbols = self.snapshots.loc[date, :].index.get_level_values(0).unique()
				
				for symbol in current_symbols:
				# for symbol in {'NESN'}:
					close_dict = self._remove_orders(date=date, title=symbol, perc=0)
					close_uncross = self._calc_uncross(bids=close_dict['bids'], asks=close_dict['asks'])
					# dump[key][symbol] = {}
					
					for p in percents:
						res = self._result_dict[key, date, symbol, p] = {}
						
						rem_dict = self._remove_orders(date=date, title=symbol, perc=p, side=side, market=mkt)
						
						dump[key].update({np.round(p,2): pd.DataFrame(rem_dict)})
						
						removed_liq = self._calc_uncross(bids=rem_dict['bids'], asks=rem_dict['asks'])
						
						res['close_price'] = close_uncross['price']
						res['close_vol'] = close_uncross['trade_vol']
						res['close_cum_bids'] = close_uncross['cum_bids']
						res['close_cum_asks'] = close_uncross['cum_asks']
						res['close_bids'] = close_uncross['total_bids']
						res['close_asks'] = close_uncross['total_asks']
						# res['close_imbalance'] = close_uncross['imbalance']
						
						res['adj_price'] = removed_liq['price']
						res['adj_vol'] = removed_liq['trade_vol']
						res['adj_cum_bids'] = removed_liq['cum_bids']
						res['adj_cum_asks'] = removed_liq['cum_asks']
						res['adj_bids'] = removed_liq['total_bids']
						res['adj_asks'] = removed_liq['total_asks']
		
		# print(">> [{0}] finished <<".format(key))
		return dump
	
	def results_to_df(self) -> pd.DataFrame:
		"""
		Export such that it can be used further in later stages.
		"""
		df = pd.DataFrame.from_dict(self._result_dict, orient='index')
		df.index.set_names(['Mode', 'Date', 'Symbol', 'Percent'], inplace=True)
		return df


class PriceDiscovery(Research):
	def __init__(self, file_snapshots, file_close_prices):
		"""
		This method needs to be initiated again because we are additionally including closing prices.
		"""
		super().__init__(file_snapshots)
		t0 = time()
		self._closeprices = pd.read_csv(file_close_prices, header=0)
		self._closeprices.set_index(['onbook_date', 'symbol'], drop=True, inplace=True)
		self._closeprices.sort_index(inplace=True)
		
		print(">>> Sub-Class initiated ({} seconds)".format(round(time() - t0, 2)))
	
	def discovery_processing(self) -> None:
		"""
		This function is supposed to exeucte the required calculations and add it to an appropriate data format.
		It calls other helper functions in order to determine the results of the analysis.
		"""
		
		# for date in ['2019-01-03']: # Alternative Looping
		for date in tqdm(self._dates):
			current_symbols = self.snapshots.loc[date, :].index.get_level_values(0).unique()
			
			for symbol in current_symbols:
				# for symbol in ['CLN']: # Alternative Looping
				sb = self._snapbook.loc[(date, symbol), :]
				close_uncross = self._calc_uncross(bids=sb['end_close_vol_bid'], asks=sb['end_close_vol_ask'])
				start_close_uncross = self._calc_uncross(bids=sb['SS_0_vol_bid'], asks=sb['SS_0_vol_ask'])
				
				preclose_uncross = self._calc_preclose(bids=sb['SS_0_vol_bid'].copy(), asks=sb['SS_0_vol_ask'])
				
				res = self._result_dict[date, symbol] = {}
				
				res['pre_abs_spread'] = preclose_uncross['abs_spread']
				res['pre_midquote'] = preclose_uncross['midquote']
				res['pre_rel_spread'] = preclose_uncross['rel_spread']
				
				res['start_price'] = start_close_uncross['price']
				res['start_vol'] = start_close_uncross['trade_vol']
				res['start_bids'] = start_close_uncross['total_bids']
				res['start_asks'] = start_close_uncross['total_asks']
				
				res['close_price'] = close_uncross['price']
				res['close_vol'] = close_uncross['trade_vol']
				res['close_bids'] = close_uncross['total_bids']
				res['close_asks'] = close_uncross['total_asks']
				
				try:
					res['actual_close_price'] = self._closeprices.loc[(date, symbol), 'price_org_ccy'].copy()
				except KeyError:
					res['actual_close_price'] = np.nan
	
	# print(">> {0} finished ({1:.2f} sec.) >>".format(date, time() - t0))
	
	def results_to_df(self) -> pd.DataFrame:
		"""
		Export such that it can be used further in later stages.
		"""
		df = pd.DataFrame.from_dict(self._result_dict, orient='index')
		df.index.set_names(['Date', 'Symbol'], inplace=True)
		df.sort_index()
		return df


class IntervalAnalysis(Research):
	def interval_processing(self) -> None:
		for date in tqdm(self._dates):
			current_symbols = self.snapshots.loc[date, :].index.get_level_values(0).unique()
			
			for symbol in current_symbols:
				SB = self._snapbook.loc[(date, symbol), :]
				SS_bids = SB.loc[:, (SB.columns.str.contains('SS_')) & (SB.columns.str.contains('_bid'))].copy()
				SS_asks = SB.loc[:, (SB.columns.str.contains('SS_')) & (SB.columns.str.contains('_ask'))].copy()
				SS_bids.rename(columns=lambda c: c.split('_')[1], inplace=True)
				SS_asks.rename(columns=lambda c: c.split('_')[1], inplace=True)
				
				if any(SS_asks.columns != SS_bids.columns):  # Check for potential errors
					raise ValueError('Columns not identical')
				else:
					lags = list(SS_asks.columns)
				
				close_uncross = self._calc_uncross(bids=SS_bids['600'], asks=SS_asks['600'])
				
				for lg in lags:
					res = self._result_dict[date, symbol, int(lg)] = {}
					snap_uncross = self._calc_uncross(bids=SS_bids[lg], asks=SS_asks[lg])
					
					res['close_price'] = close_uncross['price']
					res['close_vol'] = close_uncross['trade_vol']
					res['snap_price'] = snap_uncross['price']
					res['snap_vol'] = snap_uncross['trade_vol']
					res['snap_bids'] = snap_uncross['total_bids']
					res['snap_asks'] = snap_uncross['total_asks']
					res['snap_cum_bids'] = snap_uncross['cum_bids']
					res['snap_cum_asks'] = snap_uncross['cum_asks']
	
	def results_to_df(self) -> pd.DataFrame:
		"""
		Export such that it can be used further in later stages.
		"""
		df = pd.DataFrame.from_dict(self._result_dict, orient='index')
		df.index.set_names(['Date', 'Symbol', 'Lag'], inplace=True)
		df.sort_index(inplace=True)
		return df
