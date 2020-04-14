import os
import numpy as np
import matplotlib.pyplot as plt
import random
import time
import json

class TurbController: # Abstract class for real-time turbidostat feedback control
    id_counter = 0

    def __init__(self, setpoint=0.0, init_od=1e-6):
        self.output_limits = 0, float('inf')
        self.setpoint = setpoint
        self.od = init_od
        self.state = {'update_time': time.time(), 'od':init_od}
        self.state_history = [self.state]
        self.name = str(self.id_counter)
        self.__class__.id_counter += 1
        self.ever_updated = False

    def step(self, delta_time=None, od_meas=None, last_transfer_vol_frac=None):
        if delta_time is None: # use real time
            self.state = {'update_time': time.time()}
        else: 
            self.state = {'update_time': self._last_time() + delta_time}
        delta_time = self.state['update_time'] - self._last_time()
        transfer_vol_frac = self._step(delta_time, od_meas, last_transfer_vol_frac)
        # limit output
        min_out, max_out = self.output_limits
        transfer_vol_frac = min(max_out, max(min_out, transfer_vol_frac))
        self.state.update({'od':self.od, 'delta_time':delta_time, 'output':transfer_vol_frac})
        self.state_history.append(self.state)
        self.ever_updated = True
        return transfer_vol_frac

    def _step(self, delta_time, od_meas, last_transfer_frac=None):
        #last_transfer_frac: allow override of last command used in calculations with report of what system actually did
        pass
    
    def _last_time(self):
        return self.state_history[-1]['update_time']

    def history(self):
        return self.state_history[1:] if self.state_history else [] # omit initial state

    def last_known_od(self):
        last_state = self.state_history[-1]
        return last_state.get('od', self.od)

    def last_known_output(self):
        last_state = self.state_history[-1]
        return last_state.get('output', 0)

    def scrape_history(self, key, fill_value = None):
        return [state.get(key, fill_value) for state in self.history()]

    def __call__(self, *args, **kwargs):
        return self.step(None, *args, **kwargs) # default to real time

    def save(self, save_dir='controller_history', filename=None):
        if not os.path.exists(save_dir):
            os.mkdir(save_dir)
        if not os.path.isdir(save_dir):
            raise ValueError('Controller save directory is not a directory')
        if filename is None:
            filename = self.name + '.turbhistory'
        path = os.path.join(save_dir, filename)
        with open(path, 'w+') as f:
            f.write(json.dumps(self.state_history))

    def load(self, from_dir='controller_history', filename=None):
        if filename is None:
            filename = self.name + '.turbhistory' # go get the one with this one's name from before
        path = os.path.join(from_dir, filename)
        if not os.path.isfile(path):
            raise ValueError('No controller save history found at ' + path)
        with open(path) as f:
            self.state_history = json.loads(f.read())
        self.ever_updated = False


class ParamEstTurbCtrlr(TurbController):
    def __init__(self, setpoint=0.0, init_od=1e-6, init_k=None):
        super(ParamEstTurbCtrlr, self).__init__(setpoint, init_od)
        self.default_k = .5
        if init_k is None:
            init_k = self.default_k
        self.k_estimate = init_k
        self.state.update({'k_estimate': init_k})
        self.k_limits = .05, 3

    def predict_od(self, od_now, transfer_vol_frac, dt, k):
        # delta time (dt) is in seconds, k is in hr^-1
        return od_now*np.exp(dt/3600*k)/(1+transfer_vol_frac)

    def infer_k(self, od_then, transfer_vol_frac, od_now, dt):
        min_k, max_k = self.k_limits
        return max(min_k, min(max_k, np.log((transfer_vol_frac + 1)*od_now/od_then)/dt*3600))

    def last_known_k(self):
        last_state = self.state_history[-1]
        return last_state.get('k_estimate', self.default_k)

    def _step(self, delta_time, od_meas, last_transfer_frac=None):
        prior_od = self.last_known_od()
        last_known_out = self.last_known_output()
        prior_k = self.last_known_k()
        last_state = self.state_history[-1]
        prior_out = last_known_out if last_transfer_frac is None else last_transfer_frac
        if od_meas is not None:
            prediction = self.predict_od(prior_od, prior_out, delta_time, prior_k)
            self.od = od_meas # max(prediction - .05, min(prediction + .05, od_meas)) # clamp based on prediction to rule out crazy readings
        #error = self.predict_od(prior_od, prior_out, delta_time, prior_k) - od_meas
        if self.ever_updated: # only sensible to infer k after more than one point
            s = .15
            self.k_estimate = prior_k*(1-s) + self.infer_k(prior_od, prior_out,
                                                      self.od, delta_time)*s
            # try to close a fraction of the distance to the correct volume per iteration
            # use model to solve for perfect transfer volume, which may not be achievable
            s = .7
            transfer_vol_frac = (self.od*np.exp(delta_time/3600*self.k_estimate)
                        /((self.setpoint*s + prior_od*(1-s))) - 1)
        else:
            # play it safe
            self.k_estimate = prior_k
            transfer_vol_frac = prior_out
        # limit output
        min_out, max_out = self.output_limits
        transfer_vol_frac = min(max_out, max(min_out, transfer_vol_frac))
        self.state.update({'k_estimate':self.k_estimate})
        return transfer_vol_frac

    def set_od(self, od):
        self.od = od

if __name__ == '__main__':
    pass

