#!python3

import os
import sys
import time
import logging
import sqlite3
import csv
from turb_control import ParamEstTurbCtrlr
from types import SimpleNamespace

this_file_dir = os.path.dirname(os.path.abspath(__file__))
method_local_dir = os.path.join(this_file_dir, 'method_local')
containing_dirname = os.path.basename(os.path.dirname(this_file_dir))

def ensure_meas_table_exists(db_conn):
    '''
    Definitions of the fields in this table:
    lagoon_number - the number of the lagoon, uniquely identifying the experiment, zero-indexed
    filename - absolute path to the file in which this data is housed
    plate_id - ID field given when measurement was requested, should match ID in data file
    timestamp - time at which the measurement was taken
    well - the location in the plate reader plate where this sample was read, e.g. 'B2'
    measurement_delay_time - the time, in minutes, after the sample was pipetted that the
                            measurement was taken. For migration, we consider this to be 0
                            minutes in the absense of pipetting time values
    reading - the raw measured value from the plate reader
    data_type - 'lum' 'abs' or the spectra values for the fluorescence measurement
    '''
    c = db_conn.cursor()
    c.execute('''CREATE TABLE if not exists measurements
                (lagoon_number, filename, plate_id, timestamp, well, measurement_delay_time, reading, data_type)''')
    db_conn.commit()

def db_add_plate_data(plate_data, data_type, plate, vessel_numbers, read_wells):
    db_conn = sqlite3.connect(os.path.join(method_local_dir, containing_dirname + '.db'))
    ensure_meas_table_exists(db_conn)
    c = db_conn.cursor()
    for lagoon_number, read_well in zip(vessel_numbers, read_wells):
        filename = plate_data.path
        plate_id = plate_data.header.plate_ids[0]
        timestamp = plate_data.header.time
        well = plate.position_id(read_well)
        measurement_delay_time = 0.0
        reading = plate_data.value_at(*plate.well_coords(read_well))
        data = (lagoon_number, filename, plate_id, timestamp, well, measurement_delay_time, 
                 reading, data_type)
        c.execute('INSERT INTO measurements VALUES (?,?,?,?,?,?,?,?)', data)
    while True:
        try:
            db_conn.commit() # Unknown why error has been happening. Maybe Dropbox. Repeat until success.
            break
        except sqlite3.OperationalError:
            time.sleep(1)
        except IOError: # changed from "sqlite3.IOError". IOError is not a part of the sqlite3 library, it's a general python built-in exception. Other than that, this is perfect.
            time.sleep(1)
    db_conn.close()

from pace_util import (
    pyhamilton, HamiltonInterface, LayoutManager, ClarioStar,
    ResourceType, Plate96, Tip96, LAYFILE, PlateData,
    initialize, hepa_on, tip_pick_up, tip_eject, aspirate, dispense, read_plate,
    resource_list_with_prefix, add_robot_level_log, add_stderr_logging, log_banner)

cycle_time = 15*60 # 15 minutes
wash_vol = 250
mix_vol = 100 # uL
max_transfer_vol = 150 # uL
min_transfer_vol = 15 # uL
read_sample_vol = 75 # uL
generation_time = 30 * 60 # seconds
fixed_turb_height = 6 # mm this right for 150uL lagoons
turb_vol = 150 # uL
desired_od = 0.6
disp_height = fixed_turb_height - 1 # mm
shake_speed = 300 # RPM

def read_manifest(filename, cols_as_tuple=False):
    '''Reads in the current contents of a controller manifest; returns as dict'''
    controller_manifest = {}
    while True: # retry in case of simultaneous file access
        try:
            with open(filename+'.csv', newline='') as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    if row:
                        if cols_as_tuple:
                            controller_manifest[row[0]] = tuple(row[1:])
                        else:
                            controller_manifest[row[0]] = row[1]
            break
        except EnvironmentError:
            time.sleep(30)
            pass
    return controller_manifest

def split_in_batches(some_list, batch_len):
    def batch_gen():
        for i in range(0, len(some_list), batch_len):
            yield some_list[i:i+batch_len]
    return list(batch_gen())

def flow_rate_controller():
    min_flow_through = min_transfer_vol/turb_vol
    max_flow_through = max_transfer_vol/turb_vol
    controller = ParamEstTurbCtrlr(setpoint=desired_od, init_k=.5) # estimate for slow growing bacteria in challenging media
    if '--reset' not in sys.argv:
        try:
            controller.load() # will overwrite init k value if saved controller history is found
        except ValueError:
            pass
    controller.output_limits = min_flow_through, max_flow_through
    return controller

num_plates = 5
turb_nums = list(range(96*num_plates))
turbs_by_plate = split_in_batches(turb_nums, 96)
controllers = [flow_rate_controller() for _ in range(96*num_plates)]
controllers_by_plate = split_in_batches(controllers, 96)
helper_plate = Plate96('dummy')
manifest = read_manifest('method_local/controller_manifest')
for plate_no, ctrlr_batch in enumerate(controllers_by_plate):
    plate_key = 'plate' + str(plate_no)
    for position_idx, ctrlr in enumerate(ctrlr_batch):
        well_id = Plate96('').position_id(position_idx)
        entry_key = plate_key + ',' + well_id
        target_od = manifest.get(entry_key, None)
        if not target_od:
            print('key', entry_key, 'has no value in manifest!')
            exit()
        ctrlr.setpoint = float(target_od)

def broadcast_transfer_function(controller_batch, readings_batch):
    flow_rates = [controller(reading) for controller, reading in zip(controller_batch, readings_batch)] # step (__call__()) all controllers
    logging.info('FLOW RATES ' + str(flow_rates))
    logging.info('K ESTIMATES ' + str([controller.k_estimate for controller in controller_batch]))
    logging.info('OD ESTIMATES ' + str([controller.od for controller in controller_batch]))
    replace_vols = [rate*turb_vol for rate in flow_rates]
    logging.info('REPLACEMENT VOLUMES ' + str(replace_vols))
    return replace_vols

if __name__ == '__main__':
    local_log_dir = os.path.join(method_local_dir, 'log')
    if not os.path.exists(local_log_dir):
        os.mkdir(local_log_dir)
    main_logfile = os.path.join(local_log_dir, 'main.log')
    logging.basicConfig(filename=main_logfile, level=logging.DEBUG, format='[%(asctime)s] %(name)s %(levelname)s %(message)s')
    add_robot_level_log()
    add_stderr_logging()
    for banner_line in log_banner('Begin execution of ' + __file__):
        logging.info(banner_line)

    simulation_on = '--simulate' in sys.argv

    lmgr = LayoutManager(LAYFILE)

    reader_tray = lmgr.assign_unused_resource(ResourceType(Plate96, 'reader_tray_00002'))
    waste_site = lmgr.assign_unused_resource(ResourceType(Plate96, 'waste_site'))
    water_site = lmgr.assign_unused_resource(ResourceType(Plate96, 'water_site'))
    bleach_site = lmgr.assign_unused_resource(ResourceType(Plate96, 'bleach_site'))
    plates = resource_list_with_prefix(lmgr, 'plate_', Plate96, num_plates)
    media_sources = resource_list_with_prefix(lmgr, 'media_reservoir_', Plate96, num_plates)
    tip_boxes = resource_list_with_prefix(lmgr, 'tips_', Tip96, num_plates)

    def transfer_function(controllers_for_plate, od_readings):
        assert len(controllers_for_plate) == len(od_readings)
        return split_in_batches(broadcast_transfer_function(controllers_for_plate, od_readings), 8)

    def service(replace_vols, plate, tips, media_reservoir):
        ham_int, *_ = sys_state.instruments
        if not remember.replace_vols:
            return # no transfer volumes ready to act on
        liq_move_param = {'liquidClass':std_class, 'airTransportRetractDist':0}
        for col_num, col_vols in enumerate(replace_vols):
            array_idxs = [col_num*8 + i for i in range(8)]
            tip_poss = [(tips, j) for j in array_idxs]
            tip_pick_up(ham_int, tip_poss)
            media_poss = [(media_reservoir, j) for j in array_idxs]
            aspirate(ham_int, media_poss, col_vols, **liq_move_param)
            plate_poss = [(plate, j) for j in array_idxs]
            dispense(ham_int, plate_poss, col_vols, liquidHeight=disp_height, mixCycles=2,
                    mixVolume=mix_vol, dispenseMode=9, **liq_move_param)
            excess_vols = [max_transfer_vol for _ in media_poss]
            aspirate(ham_int, plate_poss, excess_vols,
                    liquidHeight=fixed_turb_height, **liq_move_param)
            dispense(ham_int, [(waste_site, j%8 + 88) for j in array_idxs], excess_vols, # +88 for far right side of bleach
                    liquidHeight=15, **liq_move_param)
            wash_vols = [wash_vol for _ in media_poss]
            bleach_poss = [(bleach_site, j) for j in array_idxs]
            aspirate(ham_int, bleach_poss, wash_vols, **liq_move_param)
            dispense(ham_int, bleach_poss, wash_vols, **liq_move_param)
            water_poss = [(water_site, j) for j in array_idxs]
            aspirate(ham_int, water_poss, wash_vols, **liq_move_param)
            dispense(ham_int, water_poss, wash_vols, **liq_move_param)
            tip_eject(ham_int, tip_poss)
        remember.replace_vols = None # make sure these transfers are only executed once

    with HamiltonInterface(simulate=simulation_on) as ham_int, ClarioStar() as reader_int:
        if no_reader or simulation_on:
            reader_int.disable()
        ham_int.set_log_dir(os.path.join(local_log_dir, 'hamilton.log'))
        initialize(ham_int)
        hepa_on(ham_int, 30, simulate=int(simulation_on))
        std_class = 'StandardVolumeFilter_Water_DispenseSurface_Part_no_transport_vol'
        remember = SimpleNamespace()
        remember.od_readings = None

    def measure_plate(plate, reader_protocols, simultaneously_execute=lambda:None):
        reader_protocols = [proto_name + '_fast' for proto_name in reader_protocols] # use the speed optimized versions
        ham_int, reader_int, *_ = sys_state.instruments
        platedatas = read_plate(ham_int, reader_int, reader_tray, plate, reader_protocols,
                plate_id=plate.layout_name(), async_task=simultaneously_execute)

    def convert_to_ods(platedatas, plate_template=Plate96('')):
        od_readings = []
        abs_platedata, *_ = platedatas
        for i in range(96):
            data_val = abs_platedata.value_at(*plate_template.well_coords(i))
            od = 3.2*data_val - .093 # empirical best fit line 
            # https://docs.google.com/spreadsheets/d/1YTnrmKN2TCK6aRZATgT9GmrDiO_hILrXj01NWgXDU6E/edit?usp=sharing
            # media = M9 minimal media, Volume = 150 uL
            od_readings.append(od)
        return od_readings

    def record_readings(plate, turbs_for_plate, platedatas):
        abs_platedata, *fluor_pdatas = platedatas
        list_96 = list(range(96))
        db_add_plate_data(abs_platedata, 'abs', plate, turbs_for_plate, list_96)
        for fluor_protocol, fluor_pdata in zip(('rfp', 'yfp', 'cfp'), fluor_pdatas): # mind r, y, c order
                data = [fluor_pdata.value_at(*plate.well_coords(i)) for i in list_96]
                db_add_plate_data(fluor_pdata, fluor_protocol, plate, turbs_for_plate, list_96)
                

def main():
    def service_prev_plate():
        pass # initialize to do-nothing function
    labware = plates, tip_boxes, media_sources
    items_for_each_plate = turbs_by_plate, controllers_by_plate, labware
    reader_protocols = ['kinetic_abs', 'mCherry', 'YFP', 'CFP']
    while True:
        for turbs_for_plate, controllers_for_plate, labware_for_plate in zip(items_for_each_plate):
            plate, tips, media_supply = labware_for_plate
            platedatas = measure_plate(plate, reader_protocols, simultaneously_execute=service_prev_plate)
            record_readings(plate, turbs_for_plate, platedatas)
            od_readings = convert_to_ods(platedatas) # use optical density calibration curve
            remember.replace_vols = transfer_function(controllers_for_plate, od_readings)
            def service_prev_plate(args=(plate, tips, media_supply)):
                service(remember.replace_vols, *args)

if __name__ == '__main__':
    with HamiltonInterface() as ham_int, \
            ClarioStar() as reader_int, \
            LBPumps() as pump_int:
        sys_state.instruments = ham_int, reader_int, pump_int
        system_initialize()
        main()

