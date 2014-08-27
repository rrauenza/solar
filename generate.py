#!/usr/bin/python
import csv
import datetime
import os
import sys
import xml.etree.ElementTree as ET

_SCRIPT_NAME = os.path.splitext(os.path.basename(sys.argv[0]))[0]
_IN_PGE = 'pge_electric_interval_data_8628306005_2010-07-16_to_2014-08-26.xml'
_IN_PVWATTS_SOUTH = 'pvwatts_hourly_10k_south.csv'
_IN_PVWATTS_WEST = 'pvwatts_hourly_10k_west.csv'

def _main(argv):
    pvwattsdata_south = get_pvwatts(_IN_PVWATTS_SOUTH, 0.5)
    pvwattsdata_west = get_pvwatts(_IN_PVWATTS_WEST, 0.0)
    pgedata = get_pge(_IN_PGE)
    data = merge(pgedata, pvwattsdata_south, pvwattsdata_west)
    data = bill_e1(data)
    do_report(data)


def bill_e1(data):

    ymdays = dict()
    for ts in sorted(data.keys()):
        dt = datetime.datetime.fromtimestamp(ts)
        ymdays.setdefault((dt.year, dt.month), set()).add(dt.day)

    month = None
    cumulative_usage = 0
    for ts in sorted(data.keys()):
        days = len(ymdays[(dt.year, dt.month)])
        dt = datetime.datetime.fromtimestamp(ts)
        if month != dt.month:
            month = dt.month
            cumulative_usage = 0
        usage = data[ts]['usage']
        before = apply_e1(cumulative_usage, days)
        after = apply_e1(cumulative_usage + usage, days)
        cumulative_usage += usage
        data[ts]['e1_cost_no_solar'] = after - before

    month = None
    cumulative_usage = 0
    for ts in sorted(data.keys()):
        days = len(ymdays[(dt.year, dt.month)])
        dt = datetime.datetime.fromtimestamp(ts)
        if month != dt.month:
            month = dt.month
            cumulative_usage = 0
        solar = data[ts]['solar_south'] + data[ts]['solar_west']
        usage = data[ts]['usage'] - solar
        before = apply_e1(cumulative_usage, days)
        after = apply_e1(cumulative_usage + usage, days)
        cumulative_usage += usage
        data[ts]['e1_cost_solar'] = after - before

    return data


def apply_e1(usage, days):
    if usage <= 0.0:
        return 0.0
    assert(usage >= 0.0)
    cost = 0.0
    usage /= 1000.0

    baseline = 11.0 * days

    tier1 = baseline * 1.00
    tier2 = baseline * 1.30 - tier1
    tier3 = baseline * 2.00 - tier2 - tier1

    cost += min(tier1, usage) * 0.13627
    usage -= tier1
    if usage < 0.0:
        return cost

    cost += min(tier2, usage) * 0.15491
    usage -= tier2
    if usage < 0.0:
        return cost

    cost += min(tier3, usage) * 0.31955
    usage -= tier3
    if usage < 0.0:
        return cost

    cost += usage * 0.35955
    return cost


def merge(pge, south, west):
    data = {}
    for ts in sorted(pge.keys()):
        home = pge[ts]
        dt = datetime.datetime.fromtimestamp(ts)
        key = (dt.month, dt.day, dt.hour)
        data[ts] = dict(
            datetime=dt,
            usage=home['usage'],
            solar_west=west.get(key, 0),
            solar_south=south.get(key, 0),
            actual_cost=home['cost'],
        )
    return data


def do_report(data):
    writer = csv.writer(sys.stdout)
    writer.writerow(["Date",
                     "Home Usage (watthours)",
                     "Solar West (watthours)",
                     "Solar South (watthours)",
                     "Actual Cost",
                     "E1 (no solar) Cost",
                     "E1 (solar) Cost",
                    ])
    for ts in sorted(data.keys()):
        d = data[ts]
        dt = datetime.datetime.fromtimestamp(ts)
        try:
            writer.writerow([dt,
                             d['usage'],
                             d['solar_west'],
                             d['solar_south'],
                             d['actual_cost'],
                             d['e1_cost_no_solar'],
                             d['e1_cost_solar'],
                            ])
        except KeyError:
            pass


def get_pge(filename):
    data = {}
    tree = ET.parse(open(filename))
    root = tree.getroot()
    irs = root.findall('.//{http://naesb.org/espi}IntervalBlock/{http://naesb.org/espi}IntervalReading')

    for ir in irs:
        duration = int(ir.find('{http://naesb.org/espi}timePeriod/{http://naesb.org/espi}duration').text)
        assert duration == 3600
        cost = float(ir.find('{http://naesb.org/espi}cost').text) / 100000.0
        ts = int(ir.find('{http://naesb.org/espi}timePeriod/{http://naesb.org/espi}start').text)
        watthours = int(ir.find('{http://naesb.org/espi}value').text)
        data[ts] = dict(cost=cost, usage=watthours)
    return data


def get_pvwatts(filename, scale):
    data = {}
    with open(filename) as f:
        while True:
            line = f.readline().rstrip()
            if line == '':
                break

        reader = csv.DictReader(f)
        for row in reader:
            tup = (int(row['Month']), int(row['Day']), int(row['Hour']))
            data[tup] = float(row['AC System Output (W)']) * 1 # one hour!
            data[tup] *= scale
    return data


if __name__ == "__main__":
    try:
        sys.exit(_main(sys.argv[1:]))
    except KeyboardInterrupt:
        print >> sys.stderr, '%s: interrupted' % _SCRIPT_NAME
        sys.exit(130)
