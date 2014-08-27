#!/usr/bin/python
import copy
import csv
import datetime
import dateutil
import email.utils
import os
import sys
import time
import xml.etree.ElementTree as ET

_SCRIPT_NAME = os.path.splitext(os.path.basename(sys.argv[0]))[0]
_IN_PGE = 'pge_electric_interval_data_8628306005_2010-07-16_to_2014-08-26.xml'
_IN_PVWATTS_SOUTH = 'pvwatts_hourly_10k_south.csv'
_IN_PVWATTS_WEST = 'pvwatts_hourly_10k_west.csv'


def _main(argv):
    pvwattsdata_south = get_pvwatts(_IN_PVWATTS_SOUTH, 0.3)
    pvwattsdata_west = get_pvwatts(_IN_PVWATTS_WEST, 0.3)
    pgedata = get_pge(_IN_PGE)
    pgedata = filter_by_date(pgedata,
                             datetime.datetime(2013, 8, 24, 0, 0, 0, 0),
                             datetime.datetime(2014, 8, 24, 0, 0, 0, 0))
    data = merge(pgedata, pvwattsdata_south, pvwattsdata_west)
    data = apply_solar(data)
    report = dict()
    report = bill_e1(data, report)
    report = bill_e6(data, report)
    do_report(report)


def filter_by_date(data, begin, end):
    # begin is inclusive, end isn't.
    for ts in sorted(data.keys()):
        dt = datetime.datetime.fromtimestamp(ts)
        if begin and begin > dt:
            del data[ts]
        if end and end <= dt:
            del data[ts]
    return data


def apply_solar(data):
    for ts in sorted(data.keys()):
        solar = data[ts]['solar_south'] + data[ts]['solar_west']
        solar_usage = data[ts]['usage'] - solar
        data[ts]['solar_usage'] = solar_usage
    return data


def bill_e6(data, report):

    solar = dict()
    no_solar = dict()
    ymdays = dict()

    # summarize
    for ts in sorted(data.keys()):
        dt = datetime.datetime.fromtimestamp(ts)
        ym = dt.date().replace(day=1)
        ymdays.setdefault(ym, set()).add(dt.day)
        kind = calc_e6_kind(dt)

        if ym not in solar:
            solar[ym] = dict()
        solar[ym][kind] = solar[ym].get(kind, 0) + data[ts]['solar_usage']
        solar[ym]['total'] = solar[ym].get('total', 0) + data[ts]['solar_usage']

        if ym not in no_solar:
            no_solar[ym] = dict()
        no_solar[ym][kind] = no_solar[ym].get(kind, 0) + data[ts]['usage']
        no_solar[ym]['total'] = no_solar[ym].get('total', 0) + data[ts]['usage']

    # add billing
    for ym in sorted(report.keys()):
        days = len(ymdays[ym])
        report[ym]['e6_cost_no_solar'] = apply_e6_tier(ym, no_solar[ym], days)
        report[ym]['e6_cost_solar'] = apply_e6_tier(ym, solar[ym], days)

    return report


def apply_e6_tier(dt, usage, days):
    summer = not e6_is_winter(dt)
    if summer:
        baseline = 10.9 * days
        off_tiers = ((1.0,  0.11456),
                     (1.3,  0.13778),
                     (2.0,  0.22518),
                     (None, 0.28518),
                    )
        partial_tiers = ((1.0,  0.19134),
                         (1.3,  0.21455),
                         (2.0,  0.30196),
                         (None, 0.36196),
                        )
        peak_tiers = ((1.0,  0.30661),
                      (1.3,  0.32982),
                      (2.0,  0.41723),
                      (None, 0.47723),
                     )
    else:
        baseline = 10.1 * days
        off_tiers = ((1.0,  0.11890),
                     (1.3,  0.14211),
                     (2.0,  0.22952),
                     (None, 0.28952),
                    )
        partial_tiers = ((1.0,  0.13573),
                         (1.3,  0.15894),
                         (2.0,  0.24635),
                         (None, 0.30635),
                        )

    total = usage['total']
    off = usage.get('off', 0)
    peak = usage.get('peak', 0)
    partial = usage.get('partial', 0)

    assert abs(total - (off + peak + partial)) < 0.01
    assert(total>= 0.0)

    cost = 0.0

    cost += apply_tier(off, baseline*(off/total), off_tiers)
    cost += apply_tier(partial, baseline*(partial/total), partial_tiers)

    if peak > 0:
        cost += apply_tier(peak, baseline*(peak/total), peak_tiers)

    return cost


def e6_is_winter(dt):
    if 11 <= dt.month <= 12:
        return True
    if 1 <= dt.month < 5:
        return True
    return False


def calc_e6_kind(dt):
    if dt.weekday < 5:
        weekday = True
    else:
        weekday = False
    if e6_is_winter(dt):
        # winter
        # 5-8pm weekdays
        if weekday and 17 <= dt.hour < 20:
            return 'partial'
        return 'off'
    else:
        # summer
        # 10am-1pm, m-f
        if weekday and 13 <= dt.hour < 19:
            return 'peak'
        # 7-9pm, m-f
        if weekday and 10 <= dt.hour < 13:
            return 'partial'
        # 5-9pm, Sat & Sun
        if not weekday and 17 <= dt.hour < 20:
            return 'partial'
        return 'off'
    raise Exception("oops.")


def bill_e1(data, report):

    ymdays = dict()

    # summarize
    for ts in sorted(data.keys()):
        dt = datetime.datetime.fromtimestamp(ts)
        ym = dt.date().replace(day=1)
        ymdays.setdefault(ym, set()).add(dt.day)
        for k in ('usage', 'solar_usage', 'solar_south', 'solar_west', 'actual_cost'):
            if ym not in report:
                report[ym] = dict()
            report[ym][k] = report[ym].get(k, 0) + data[ts][k]

    # add billing
    for ym in sorted(report.keys()):
        days = len(ymdays[ym])
        report[ym]['e1_cost_no_solar'] = apply_e1_tier(report[ym]['usage'], days)
        report[ym]['e1_cost_solar'] = apply_e1_tier(report[ym]['solar_usage'], days)

    return report


def apply_tier(usage, baseline, tiers):

    usage /= 1000.0

    tier1 = baseline * tiers[0][0]
    tier2 = baseline * tiers[1][0] - tier1
    tier3 = baseline * tiers[2][0] - tier2 - tier1
    assert(tiers[3][0] is None)

    p1 = tiers[0][1]
    p2 = tiers[1][1]
    p3 = tiers[2][1]
    p4 = tiers[3][1]

    cost = 0.0

    cost += min(tier1, usage) * p1
    usage -= tier1
    if usage < 0.0:
        return cost

    cost += min(tier2, usage) * p2
    usage -= tier2
    if usage < 0.0:
        return cost

    cost += min(tier3, usage) * p3
    usage -= tier3
    if usage < 0.0:
        return cost

    cost += usage * p4
    return cost


def apply_e1_tier(usage, days):
    if usage <= 0.0:
        return 0.0
    assert(usage >= 0.0)

    baseline = 11.0 * days

    return apply_tier(usage, baseline,
        (
            (1.00,  0.13627),
            (1.30,  0.15491),
            (2.00,  0.31955),
            (None,  0.35955),
        ))


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


def do_report(report):
    writer = csv.writer(sys.stdout)
    writer.writerow(["Date",
                     "Home Usage (watthours)",
                     "Solar West (watthours)",
                     "Solar South (watthours)",
                     "Actual Cost",
                     "E1 (no solar) Cost",
                     "E1 (solar) Cost",
                     "E6 (no solar) Cost",
                     "E6 (solar) Cost",
                    ])
    rows = ('usage',
            'solar_west',
            'solar_south',
            'actual_cost',
            'e1_cost_no_solar',
            'e1_cost_solar',
            'e6_cost_no_solar',
            'e6_cost_solar',
           )

    totals = dict()

    for dt in sorted(report.keys()):
        d = report[dt]
        try:
            rd = [ dt, ]
            for r in rows:
                value = d[r]
                totals[r] = totals.get(r, 0) + value
                if isinstance(value, float):
                    value = "%0.2f" % value
                rd.append(value)
            writer.writerow(rd)
        except KeyError:
            pass

    rd = [ 'total', ]
    for r in rows:
        try:
            value = totals[r]
            if isinstance(value, float):
                value = "%0.2f" % value
            rd.append(value)
        except KeyError:
            rd.append('?')

    writer.writerow(rd)


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
