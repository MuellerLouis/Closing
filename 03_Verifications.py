from cls_ClosingCalc import *
from cls_VerificationPlots
import seaborn as sns
import matplotlib.pyplot as plt

pd.set_option('display.width', 180)
pd.set_option("display.max_columns", 8)

########################################################################
file_snapshots = os.getcwd() + "\\Data\\20190315_closing_orders.csv"
file_prices = os.getcwd() + "\\Data\\orders_closing_prices.csv"
mode = 'Sensitivity'
percent = np.arange(0, 0.3, 0.05)
########################################################################


Sens = SensitivityAnalysis(file_snapshots)

bid_dump = Sens.sens_analysis(key='bid_limit', percents=percent, dump=True)
ask_dump = Sens.sens_analysis(key='ask_limit', percents=percent, dump=True)
all_dump = Sens.sens_analysis(key='all_limit', percents=percent, dump=True)
# Sens.export_results('Verification_v1', 'csv')


def plot_closing_orders(dump, stock, date='2019-03-15'):
	dic = dump[date][stock]

	for p in iter(dic):
		fig, ax = plt.subplots(1, 1, )

print("<<< Sensitivity Sens complete >>>")


