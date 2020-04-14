import datetime as dt
import os
import sys
import csv

do_plot = '--plot' in sys.argv
do_export = '--noexport' not in sys.argv
include_all = '--all' in sys.argv

'''
Hi Emma! Use this with no arguments to create getlogstuff_output.csv and do your R magic to it.
It automatically attempts to only output the chunk of data corresponding to the last real experiment run with real data. If you don't want it to be smart and just want everything in the whole log, just use the --all switch, i.e.
    py getlogstuff.py --all
'''

if do_plot:
    from matplotlib import pyplot as plt

csv_rows = []

with open(os.path.join('..', 'method_local', 'log', 'main.log')) as f:
    lines = [l for l in f]
    print(lines[0])
def process_token(token):
    split_token = ' root INFO ' + token + ' '
    contiguous_blocks = [[]]
    num_plates = 3
    last_time = start_time = None
    plate_rotation = 0
    build_data = []
    for line in lines:
        if split_token in line:
            plate_rotation = (plate_rotation + 1) % num_plates
            time_str, data = line.split(split_token)
            time = dt.datetime.strptime(time_str, '[%Y-%m-%d %H:%M:%S,%f]')
            #if last_time:
            #    print((time - last_time).seconds)
            if last_time and (include_all or (time - last_time).seconds > 30*60):
                contiguous_blocks.append([])
            current_block = contiguous_blocks[-1]
            #print(len(current_block))
            if not current_block:
                start_time = time
            delta_time = time - start_time
            build_data += eval(data)
            if plate_rotation == 0:
                print(len(build_data))
                current_block.append((delta_time.seconds/3600+delta_time.days*24, build_data))
                build_data = []
            last_time = time

    # expected shape of contiguous_blocks for some particular split token:
    # dim 1: Number of different experiment runs separated by an hour, or more, maybe 3-5
    # dim 2: Varies; number of time points in each of those separated blocks
    # dim 3: 2. One time, a float, and a list of data.
    # dim 4: (For the first element, the time, n/a.) For the second element: 96, or however many vessels there are.
    #print(len(contiguous_blocks[-1]))
    #print(len(contiguous_blocks[-1][0]))
    #print(len(contiguous_blocks[-1][0][1]))
    #print(len(contiguous_blocks[-1][0][1][0]))
    #print('those ^ three things')
    #print(len(contiguous_blocks))
    #print(time)
    #print(start_time)
    last_block = []
    while len(last_block) < 5:
        last_block = contiguous_blocks.pop()
    print(last_block)
    times, datablock = zip(*last_block)
    print(times)
    if do_export:
        cols = [([] if csv_rows else ['hours']) + list(times),
                ([] if csv_rows else ['datatype']) + [token.replace(' ', '') for _ in times]]
        for turbnum, time_course in enumerate(zip(*datablock)):
            cols.append(([] if csv_rows else ['turb_' + str(turbnum)]) + list(time_course))
        for row in zip(*cols):
            csv_rows.append(row)
    if do_plot:
        plt.figure(token)
        # print(token)
        for time_course in zip(*datablock):
            plt.plot(times, time_course)

for token in 'OD ESTIMATES', 'K ESTIMATES', 'REPLACEMENT VOLUMES', 'CONVERTED OD READINGS', 'FLUORESCENCE RFP READINGS', 'FLUORESCENCE YFP READINGS', 'FLUORESCENCE CFP READINGS':
    process_token(token)
    
if do_export:
    print('exporting')
    with open('getlogstuff_output.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        for row in csv_rows:
            writer.writerow(row)
if do_plot:
    plt.show()
