"""
TODO: this will replace the code that ran on the MongoDB side of the old GeoQuery.

* code below is an initial rough port of the original script, but it is not tested yet and will require adjustments to work with the new Django models and database structure.
"""

import os
import datetime
import pandas as pd
import numpy as np
from pathlib import Path

from datasets.models import Dataset, DatasetResource, Mapping
from features.models import Feature, FeatMap, FeatureCollection
from analytics.models import ExtractTask, ExtractData, ProcessingOption, Request, RequestMap, Coverage


mode = "all"
# mode = "nowm"


base_path = Path("/home/smgoodman/stats")

output_path = base_path / "outputs"
output_path.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------------
#  generate basic request level stats

if mode == "all":
    requests = Request.objects.filter(status=1, submit_time__gt=1486443600)
elif mode == "nowm":
    requests = Request.objects.filter(status=1, submit_time__gt=1486443600, contact__regex=r"^(?!.*wm.edu)(?!.*aiddata.org)")
else:
    raise ValueError(f"Invalid mode (`{mode}`)")

csv_data = []

for r in requests:
    row_dict = {
        "contact": r.contact,
        "submit_time": r.submit_time,
        "complete_time": r.complete_time
    }
    csv_data.append(row_dict)


request_df = pd.DataFrame(csv_data)

request_df = request_df[["contact", "submit_time", "complete_time"]]

request_path = output_path / f"{mode}_user_data.csv"

request_df.to_csv(request_path, index=False, encoding="utf-8")

request_df["requests"] = 1

# -----------------------------------------------------------------------------
# generate count of requests for each feature collection

# boundary_df = request_df.groupby("boundary_title", as_index=False).agg({
#     "requests": "sum"
# }).sort_values(by="requests", ascending=False)

# boundary_path = output_path / f"{mode}_boundary_request_count.csv"
# boundary_df.to_csv(boundary_path, index=False, encoding="utf-8")


# -----------------------------------------------------------------------------
# generate count of times each dataset is requested

dataset_requests = Request.objects.filter(status=1, submit_time__gt=1486443600)
dataset_names = []

for r in dataset_requests:
    for i in r["raster_data"]:
        if i:
            dataset_names.append(i["name"])

dataset_values, dataset_counts = np.unique(dataset_names, return_counts=True)

dataset_df = pd.DataFrame({"name": dataset_values, "requests": dataset_counts}).sort_values(by="requests", ascending=False)

dataset_path = output_path / f"{mode}_dataset_request_count.csv"
dataset_df.to_csv(dataset_path, index=False, encoding="utf-8")


# -----------------------------------------------------------------------------
#  generate monthly and weekly aggregation of requests

request_df["timestamp"] = request_df["submit_time"]

fts = datetime.datetime.fromtimestamp

request_df["datetime"] = request_df["timestamp"].apply(lambda z: fts(z))

request_df["month"] = request_df["datetime"].apply(lambda z: "{0}{1}".format(z.year, str(z.month).zfill(2)))

# request_df["week"] = request_df["datetime"].apply(lambda z: "{0}{1}{2}".format(z.year, str(z.month).zfill(2), z.strftime("%U")))

def weekly_transform(z):
    try:
        # day of year representing the week of the year
        start_of_week = int(z.strftime("%U")) * 7
        start_of_week = start_of_week + 1 if start_of_week == 0 else start_of_week
        year_day_str = "{0} {1}".format(z.year, str(start_of_week).zfill(3))
        year_day_obj = datetime.datetime.strptime(year_day_str, "%Y %j")
        year_day_formatted = year_day_obj.strftime("%Y%m%d")
        return year_day_formatted
    except:
        return None

request_df["week"] = request_df["datetime"].apply(lambda z: weekly_transform(z))

request_df["day"] = request_df["datetime"].apply(lambda z: z.strftime("%Y%m%d"))

monthly_request_df = request_df[["month", "requests"]].groupby(["month"], as_index=False).sum()
weekly_request_df = request_df[["week", "requests"]].groupby(["week"], as_index=False).sum()
daily_request_df = request_df[["day", "requests"]].groupby(["day"], as_index=False).sum()

# monthly_request_path = os.path.join(output_path, "geoquery_requests_monthly.csv")
# weekly_request_path = os.path.join(output_path, "geoquery_requests_weekly.csv")

# monthly_request_df.to_csv(monthly_request_path, index=False, encoding="utf-8")
# weekly_request_df.to_csv(weekly_request_path, index=False, encoding="utf-8")


# -----------------------------------------------------------------------------
#  generate user aggregation of request counts (current, and weekly/monthly)

user_df = request_df.groupby("contact", as_index=False).agg({
    "requests": "sum"
})

user_path = output_path / f"{mode}_user_request_count.csv"
user_df.to_csv(user_path, index=False, encoding="utf-8")


monthly_user_df = request_df[["month", "contact"]].groupby(["month"], as_index=False).agg({"contact":pd.Series.nunique})
monthly_user_df.columns = ["month", "users"]

weekly_user_df = request_df[["week", "contact"]].groupby(["week"], as_index=False).agg({"contact":pd.Series.nunique})
weekly_user_df.columns = ["week", "users"]

daily_user_df = request_df[["day", "contact"]].groupby(["day"], as_index=False).agg({"contact":pd.Series.nunique})
daily_user_df.columns = ["day", "users"]


# -----------------------------------------------------------------------------


monthly_df = monthly_request_df.merge(monthly_user_df, on="month")
monthly_df["datetime"] = monthly_df["month"].apply(lambda z: datetime.datetime.strptime(z, "%Y%m"))

monthly_path = os.path.join(output_path, "{}_geoquery_monthly.csv".format(mode))
monthly_df.to_csv(monthly_path, index=False, encoding="utf-8")


weekly_df = weekly_request_df.merge(weekly_user_df, on="week")
weekly_df["datetime"] = weekly_df["week"].apply(lambda z: datetime.datetime.strptime(z, "%Y%m%d"))

weekly_path = os.path.join(output_path, "{}_geoquery_weekly.csv".format(mode))
weekly_df.to_csv(weekly_path, index=False, encoding="utf-8")


daily_df = daily_request_df.merge(daily_user_df, on="day")
daily_df["datetime"] = daily_df["day"].apply(lambda z: datetime.datetime.strptime(z, "%Y%m%d"))

daily_path = os.path.join(output_path, "{}_geoquery_daily.csv".format(mode))
daily_df.to_csv(daily_path, index=False, encoding="utf-8")


# -----------------------------------------------------------------------------

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


event_dates = [
    # 20191022, # nethope
    # 20191113, # aidex
]

# date_ranges = [
#     [20190901, 20191120]
# ]

min_date = 20170101
max_date = 20500101

min_datetime = datetime.datetime.strptime(str(min_date), "%Y%m%d")
max_datetime = datetime.datetime.strptime(str(max_date), "%Y%m%d")

monthly_plot_df = monthly_df.loc[(monthly_df.datetime >= min_datetime) & (monthly_df.datetime <= max_datetime)].copy(deep=True).reset_index()
weekly_plot_df = weekly_df.loc[(weekly_df.datetime >= min_datetime) & (weekly_df.datetime <= max_datetime)].copy(deep=True).reset_index()
daily_plot_df = daily_df.loc[(daily_df.datetime >= min_datetime) & (daily_df.datetime <= max_datetime)].copy(deep=True).reset_index()

# monthly_plot_df = monthly_df.copy(deep=True)
# weekly_plot_df = weekly_df.copy(deep=True)
# daily_plot_df = daily_df.copy(deep=True)



plt.figure(figsize=(6,3))
plt.plot("month", "users", data=monthly_plot_df, linewidth=1, color="skyblue", label="users")
plt.plot("month", "requests", data=monthly_plot_df, linewidth=1, color="red", label="requests")
plt.legend()
plt.xticks(rotation=60)
plt.tight_layout()

ax = plt.axes()
ax.xaxis.set_major_locator(plt.MaxNLocator(20))

monthly_plot_path = os.path.join(output_path, "{}_geoquery_monthly_plot.png".format(mode))
plt.savefig(monthly_plot_path)


plt.figure(figsize=(6,3))
plt.plot("week", "users", data=weekly_plot_df, linewidth=1, color="skyblue", label="users")
plt.plot("week", "requests", data=weekly_plot_df, linewidth=1, color="red", label="requests")
plt.legend()
plt.xticks(rotation=60)
plt.tight_layout()

ax = plt.axes()
ax.xaxis.set_major_locator(plt.MaxNLocator(20))

weekly_plot_path = os.path.join(output_path, "{}_geoquery_weekly_plot.png".format(mode))
plt.savefig(weekly_plot_path)


plt.figure(figsize=(10,4))
plt.plot("day", "users", data=daily_plot_df, linewidth=1, color="skyblue", label="users")
plt.plot("day", "requests", data=daily_plot_df, linewidth=1, color="red", label="requests")
plt.legend()
plt.xticks(rotation=60)
plt.tight_layout()

vlines = []
vlines = vlines + event_dates
for v in vlines:
    v1 = daily_plot_df.loc[daily_plot_df.day == str(v)].index[0]
    plt.axvline(x=v1, linewidth=1, color="black", linestyle="--")

ax = plt.axes()
ax.xaxis.set_major_locator(plt.MaxNLocator(15))

daily_plot_path = output_path / f"{mode}_geoquery_daily_plot.png"
plt.savefig(daily_plot_path)



# -----------------------------------------------------------------------------

# iterate over monthly steps

min_requests = 1

start = 1486443600

date_format = "%Y-%m-%d"

start_ymd = datetime.datetime.fromtimestamp(start).strftime(date_format)
current_ymd = datetime.datetime.now().strftime(date_format)

time_steps  = pd.date_range(start_ymd, current_ymd, freq="M")

repeat_df = pd.DataFrame({"month_ts": time_steps, "count": 0, "gain": 0, "total": 0})

for ix, step_ts in enumerate(repeat_df["month_ts"]):
    repeat_df.loc[ix, "month"] = step_ts.strftime("%Y%m")
    # convert timestamp obj to int
    # add 24 hours to get end of day
    step_timestamp = step_ts.timestamp() + (24*60*60)
    # run aggregation query
    # agg = c_det.aggregate([
    #     {"$match": {"stage.0.time": {"$gt": start}, "stage.3.time": {"$lt": step_timestamp}}},
    #     {"$group": {"_id": "$contact", "count": {"$sum": 1}}},
    #     {"$match": {"count": {"$gt": min_requests}}}
    # ])
    agg = Request.objects.filter(submit_time__gt=start, complete_time__lt=step_timestamp).values("contact").annotate(count=Count("id")).filter(count__gt=min_requests)
    n_repeat = int(len(list(agg)))
    repeat_df.loc[ix, "count"] = n_repeat
    if ix > 0:
        repeat_df.loc[ix, "gain"] = n_repeat - repeat_df.loc[ix-1, "count"]
    total_users = Request.objects.filter(submit_time__gt=start, complete_time__lt=step_timestamp).values_list("contact", flat=True)
    repeat_df.loc[ix, "total"] = len(total_users)


repeat_df = repeat_df[["month", "count", "gain", "total"]]
repeat_path = output_path / f"{mode}_repeat_list.csv"
repeat_df.to_csv(repeat_path, index=False, encoding="utf-8")
