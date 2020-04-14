import os
import sys
turb_ctrl_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if turb_ctrl_path not in sys.path:
    sys.path.append(turb_ctrl_path)

from turb_control import ParamEstTurbCtrlr
import numpy as np
import matplotlib.pyplot as plt
import random
import time
import threading

class SimTurbidostat:
    def __init__(self, controller, cycle_time, setpoint=0.0, init_od=None, growth_k=2.08): # commonly cited double every 20 minutes
        self.cycle_time = cycle_time # in seconds
        self.growth_k = growth_k # ground truth k (hrs^-1), different from controller k estimate
        if init_od is None:
            init_od = controller.last_known_od()
        else:
            self = init_od # ground truth od, different from controller od
        self.od = init_od/(1 + controller.last_known_output())
        controller.output_limits = .05, .68
        controller.setpoint = setpoint
        self.controller = controller
        self.wait_thread = None

    def update(self, realtime=False):
        if self.wait_thread: # use threading for delays to allow multiple simultaneous real-time simulations
            self.wait_thread.join()
        # grow culture
        self.od = self.od*np.exp(self.cycle_time/3600*self.growth_k)
        delta_time = None if realtime else self.cycle_time
        meas_noise = rand_between(-.005, .005) + .1/(1+random.random()*10000) # Occasional very large spikes, as when clumps occlude sensor
        if delta_time:
            transfer_vol_frac = self.controller.step(delta_time, self.od + meas_noise)
        else:
            transfer_vol_frac = self.controller(self.od + meas_noise) # exercise callable functionality
        # add mechanical/operational noise
        actual_transfer_vol_frac = transfer_vol_frac + rand_between(-.01, .01)
        # dilute according to command
        self.od = self.od/(1+actual_transfer_vol_frac)
        if realtime:
            self.wait_thread = threading.Thread(target=lambda: time.sleep(cycle_time))
            self.wait_thread.start() 

    def set_k(self, k):
        self.growth_k = k

    def set_od(self, od):
        self.od = od

def rand_between(a, b):
    return min(a,b) + random.random()*abs(b-a)

realtime = '--realtime' in sys.argv
load = '--load' in sys.argv

if __name__ == '__main__':
    normal_cycle_time = 15*60 # 15 mins in seconds
    if realtime:
        cycle_time = .1
    else:
        cycle_time = normal_cycle_time

    xs = []
    controllers = [ParamEstTurbCtrlr(init_k=.45) for _ in range(24)]
    if load:
        for controller in controllers:
            try:
                controller.load(from_dir='sim_controller_history')
            except ValueError:
                pass
    sim_turbs = [SimTurbidostat(ctrlr, cycle_time) for ctrlr in controllers]

    def get_history(turb, key):
        return [state.get(key, 0) for state in turb.controller.history()]

    def plotem():
        od_courses, output_courses, k_courses = ([st.controller.scrape_history(key) for st in sim_turbs] for key in ('od', 'output', 'k_estimate'))
        #print(k_courses)
        plt.plot(xs, list(zip(*od_courses)))
        plt.figure()
        plt.plot(xs, list(zip(*output_courses)))
        plt.figure()
        plt.plot(xs, list(zip(*k_courses)))
        plt.show()

    try:
        for w, sim_turb in enumerate(sim_turbs):
            sim_turb.setpoint = .45
            if not load:
                sim_turb.set_od(rand_between(.0002, .5))
            time_norm = normal_cycle_time*10 if realtime else 1
            if realtime:
                sim_turb.controller.k_limits = .05, 25000
            if w < 12:
                # linear range between 2 bounds
                sim_turb.set_k((w/12*.3 + (12-w)/12*.5)*time_norm)
            else:
                # linear range between 2 bounds
                w -= 12
                sim_turb.set_k((w/12*1.1 + (12-w)/12*1.3)*time_norm)

        for i in range(100 if realtime else 200):
            try:
                tooth_size = 40
                if i % tooth_size == 0:
                    tooth_height = .02 + rand_between(0,.06)
                    for w, sim_turb in enumerate(sim_turbs):
                        sim_turb.controller.setpoint = (i%(tooth_size*2)/tooth_size)*tooth_height+.4
                        #print((i%(tooth_size*2)/tooth_size)*tooth_height+.4)
                for sim_turb in sim_turbs:
                    sim_turb.update(realtime=realtime)
                print('cycle:', i)
                #time.sleep(cycle_time/sim_time_dilation)
            except KeyboardInterrupt:
                import pdb; pdb.set_trace()

        xs = [i*normal_cycle_time/3600 for i in range(len(sim_turbs[0].controller.history()))]

        plotem()
    finally:
        for sim_turb in sim_turbs:
            sim_turb.controller.save(save_dir='sim_controller_history')

