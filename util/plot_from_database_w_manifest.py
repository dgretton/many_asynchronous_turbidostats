import sqlite3
import matplotlib.pyplot as plt
from datetime import datetime
import pdb
import sys
import os
import csv
import matplotlib.patches as mpatches
import matplotlib
import random
import numpy as np

number_of_wells = 96

def well_data(well, type):
    '''Fetches data of type (lum, abs) for a particular well and plots it on the graph'''
    n = (well, type, )
    c.execute('SELECT filename, well, reading FROM measurements WHERE well=? AND data_type=?', n)

    x = c.fetchall()
    print(len(x), "entries fetched")
    vals = [(datetime.strptime(f[-15:-4], '%y%m%d_%H%M'), w, 5.40541*data_val - 0.193514) for (f, w, data_val) in x if 'dummy' not in f]
    t_vals = [t for t, w, v in vals] 
    return [(t, w, v) if v < .7 else (t, w, np.nan) for t, w, v in vals] 

def line_plot_well(well, type, plt, color = 'b', linewidth = 1, linestyle = '.-'):
    vals = well_data(well, type)
    plt.plot([j for (j, _, _) in vals], [lum for (j, _, lum) in vals], color = color, linestyle = linestyle, linewidth=linewidth, marker = 'o', markersize = 1.5)
    
    # decrease number of plotted X axis labels
    # make there be fewer labels so that you can read them
    times = [x for (x, _, _) in vals]
    deltas = [t - times[0] for t in times]
    labels = [int(d.seconds/60/60 + d.days*24) for d in deltas]
    labels_sparse = [labels[x] if x % 6 == 0 else '' for x in range(len(labels))]
    plt.xticks(times, labels_sparse)
    locs, labels = plt.xticks()

# automatically find the database file for this 96-robot method
db_dir = os.path.join('..', 'method_local')

if len(sys.argv) > 2:
    print('Only (optional) argument is the name of the database you want to plot from')
    exit()
dbs = [filename for filename in os.listdir(db_dir) if filename.split('.')[-1] == 'db']
if len(sys.argv) == 2:
    db_name = sys.argv[1]
    if db_name not in dbs:
        print('database does not exist in ' + db_dir)
        exit()
else:
    if len(dbs) != 1:
        print('can\'t infer which database you want to plot from, please specify with argument')
        exit()
    db_name, = dbs

conn = sqlite3.connect(os.path.join(db_dir, db_name))
c = conn.cursor()

# read in the manifest file
# assign colors to the types as they arise
colors = list(matplotlib.colors.cnames.items())
random.shuffle(colors)
colors = [name for name,hex in colors]

# read in manifest file
csvfile = open('Manifest.csv', 'r')
reader = csv.reader(csvfile)
manifest = {}
well_phage = {}
for row in reader:
    (plate, well, type, phage) =  row[:4]
    
    if type not in manifest:
        manifest[type] = [well]
    else:
        manifest[type].append(well)
    well_phage[well] = type

'''
# 96-plot
for measurement_type in ['lum', 'abs']:
    scale = 2
    fig1 = plt.figure(figsize=(24*scale, 16*scale))
    subplot = 0
    for column in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
        for row in range(1,13):
            subplot = subplot + 1
            well = column + str(row)

            # set up plot
            ax = fig1.add_subplot(8, number_of_wells/8, subplot)
            ax.set_title("Lagoon" + str(well) + ': ' + well_phage[well], x=0.5, y=0.8)

            # did this well have phage? if so, plot in red
            color = 'r'
            if well_phage[well] == "no phage control":
                color = 'b'
            
            # plot a single well
            plot_well(well, measurement_type, plt, color = color, linestyle = 'solid', linewidth = 7)
    
            # adjust limit values to reflect the type of graph
            if measurement_type == 'abs':
                plt.ylim(0.0, 1.0)
            else:
                ax.set_yscale('log')
                plt.ylim(200.0, 100000.0)
        
    fig1.tight_layout()
    plt.savefig(os.path.join(db_dir, 'manifest_plot_' + measurement_type + ".png"), dpi = 200)
'''

# manifest plot
for measurement_type in ['lum', 'abs']:
    fig2 = plt.figure()
    
    # plot the data one type at a time
    i = 0
    patches = []
    for i, (type, wells) in enumerate(manifest.items()):
        i = i + 1

        all_type_data = []
        for well in wells:
            # aggregate data
            all_type_data.append(well_data(well, measurement_type))
            # plot one well at a time
            ls = 'solid'
            #line_plot_well(well, measurement_type, plt, color = colors[i%len(colors)], linestyle = ls, linewidth = 1)
        color = colors[i%len(colors)]
        patches.append(mpatches.Patch(color=color, label=type))

        times = [[t for (t, w, v) in data_tups] for data_tups in all_type_data][0]
        if not times:
            continue
        vals = [[v for (t, w, v) in  data_tups] for data_tups in all_type_data]
        avgs = np.array([np.nanmean(vs) for vs in zip(*vals)])
        stds = np.array([np.nanstd(vs) for vs in zip(*vals)])
        print(avgs)
        plt.plot(times, avgs, color=color, alpha=.8)
        plt.fill_between(times, avgs + stds, avgs - stds, color=color, alpha=.2, linewidth=0)
        plt.fill_between(times, avgs + 2*stds, avgs - 2*stds, color=color, alpha=.2, linewidth=0)
        deltas = [t - times[0] for t in times]
        labels = [int(d.seconds/60/60 + d.days*24) for d in deltas]
        labels_sparse = [labels[x] if x % 6 == 0 else '' for x in range(len(labels))]
        plt.xticks(times, labels_sparse)
        # add the legend item

    # plot the legend
    #plt.legend(handles=patches, loc='upper left')
    plt.legend(handles=patches, bbox_to_anchor=(1,.1), loc="lower right", 
                bbox_transform=fig2.transFigure, ncol=3)

    plt.xlabel("Hours")
    plt.ylabel(measurement_type)
    if measurement_type == 'lum':
        plt.title("Luminescence monitoring")
        plt.axhline(y=450, color='r')
    else:
        plt.title("Absorbance monitoring")
        plt.axhline(y=.45, color='tomato')
        
    # adjust limit values to reflect the type of graph
    if measurement_type == 'abs':
        plt.ylim(0.0, 0.7)
        plt.gca().set_aspect(1/2)
    else:
        #plt.ylim(350.0, 4000.0)
        fig2.get_axes()[0].set_yscale('log')
        plt.autoscale(enable=True, axis='y')
    
    #fig2.tight_layout()
    plt.savefig(os.path.join(db_dir, 'manifest_single_plot_' + measurement_type + ".png"), dpi = 200, bbox_inches="tight")

conn.close()
