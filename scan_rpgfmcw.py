# -*- coding: utf-8 -*-
"""
Created on Wed Dec  6 13:44:33 2023

@author: Toshiba
"""
import os
import time
import sys
import glob
import datetime
import warnings
import numpy as np

from RPGtools_RemoteSensingInstruments.RadarControl import (Scan,
                                                            Client,
                                                            MeasDefFile,
                                                            MeasBatchFile,
                                                            install_local_mdf,
                                                            get_radar_status,
                                                            start_radar_measurements_local_mdf,
                                                            start_radar_measurements,
                                                            install_local_mdf)

WORKDIR = os.path.abspath('.')
WORKDIR = r'C:\RPG-FMCW-H\MDF_MBF'
WORKDIR = WORKDIR if WORKDIR.endswith(os.sep) else WORKDIR + os.sep

##################################
### RADAR SPECIFIC SETTINGS ######
##################################
IP = '192.168.0.2'
PORT = 7000
PW = ''
CONFIG = [IP, PORT, PW]

##################################
### SCAN SPECIFIC SETTINGS ###
##################################
SCANSPEED = 1
FASTSPEED = 5

##################################
### CHIRP SPECIFIC SETTINGS ######
##################################
CHIRPPRG = 7  # RMBLCHIRP, the inface number starts at 1, the real list at 0


##################################
### LOCATION SPECIFIC SETTINGS ###
##################################
NORTHOFFSET = 22.3


##################################
### CLOUDLAB SPECIFIC SETTINGS ###
##################################
# default duration is in s
DURATION = 20 * 60
# EXTRAWAIT = 10 # an extra number of seconds to wait for the scan to be done
# at the end of a scan, wait this amount in seconds before sending a new scan cmd
AFTERSCANWAIT = 5

##################################
### RPG SPECIFIC SETTINGS ###
##################################
t0 = datetime.datetime(2001, 1, 1, tzinfo=datetime.UTC)
asec = datetime.timedelta(seconds=1)
amin = 60 * asec


def _ts2dt(seconds, milliseconds=0):
    if seconds is None:
        return None
    dts = (datetime.timedelta(seconds=seconds),
           datetime.timedelta(seconds=milliseconds/10**6))
    return t0 + dts[0] + dts[1]


# get current measurement time from sample
def _get_cmt(sample):
    return _ts2dt(sample.samp_t, milliseconds=sample.samp_ms)


# get end of measurement from sample
def _get_eom(sample):
    eom = getattr(sample, 'end_of_meas', None)
    if eom is None:
        return None
    return _ts2dt(eom)


def report(client,
           duration=None,
           reportfrequency=1,
           break_on_eom=False):
    start = datetime.datetime.now(datetime.UTC)
    if isinstance(duration, float) or isinstance(duration, int):
        duration = datetime.timedelta(seconds=duration)

    cnt = 0
    try:
        while True:
            _sample = client.get_last_sample()
            cmt = _get_cmt(_sample)
            print('Time of sample:', cmt)
            print('Current elevation/elv speed:',
                  f'{_sample.elv:4.3}°, {_sample.inc_el:3.3}°/s'
                  )
            print('Current azimuth/az speed:',
                  f'{_sample.azm:4.3}°, {_sample.inc_elax:3.3}°/s'
                  )
            # so we do not have to see the empty slice warnings for nans
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                print('Current min, mean and max ZE:',
                      f'{np.nanmin(_sample.ze):5.3} dBZ',
                      f'{np.nanmean(_sample.ze):5.3} dBZ',
                      f'{np.nanmax(_sample.ze):5.3} dBZ'
                      )
                print('Current min, mean and max SLDR:',
                      f'{np.nanmin(_sample.sldr):5.3} dB',
                      f'{np.nanmean(_sample.sldr):5.3} dB',
                      f'{np.nanmax(_sample.sldr):5.3} dB'
                      )

            now = datetime.datetime.now(datetime.UTC)
            if duration is not None and (now - start) > duration:
                break

            eom = _get_eom(_sample)

            if eom is not None and break_on_eom and now > (eom + 10 * asec):
                print(f'Ending reporting as {eom} has passed {now}')
                break

            time.sleep(reportfrequency)
            cnt += 1

    except KeyboardInterrupt:
        return


def ensure_termination(client,
                       timeout=20,
                       retrytime=0.5,
                       quiet=True):
    res = -1
    cnt = 0
    while res != 1:
        if not quiet:
            print(f'Trying to terminate measurements (try {cnt+1})')
        res = client.terminate_radar_measurements()

        if res in [3, 4]:
            print('Zero calibration cannot be determinated, wait longer...')
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                print('Waiting cancelled')
                return
        elif res in [5]:
            print('Transmitter calibration cannot be determinated, wait longer...')
            time.sleep(10)

        time.sleep(retrytime)
        cnt += 1
        _status = client.get_radar_status()
        # print('Current status after termination command:', _status.__dict__)
        if cnt * retrytime >= timeout:
            print('Measurement could not be terminated in ',
                  f'{cnt*retrytime} seconds, use GUI')
            return

    # to ensure there is enough time for the radar to react
    time.sleep(2)


def ensure_start(client,
                 file,
                 timeout=30,
                 retrytime=2,
                 quiet=True):

    res = -1
    cnt = 0
    client.terminate_radar_measurements()
    while res != 1:
        if not quiet:
            print(f'Trying to start measurements (try {cnt+1})')

        # if the file exists we assume it is a local file that we do once
        # else we assume it is on the radar in the default MDF/MBF directory
        if os.path.exists(file):
            # assume its local and we need to send it
            res = client.start_radar_measurements_local_mdf(file)
        else:
            # assume its on the radar
            res = client.start_radar_measurements(file)

        # if res == 2:
        #     ensure_termination(client, quiet=quiet)

        time.sleep(retrytime)
        cnt += 1
        _status = client.get_radar_status()
        if 'mdf_name' in _status.__dict__:
            curmdf = _status.mdf_name

            if isinstance(curmdf, list):
                curmdf = curmdf[0]

            if file.lower().endswith(curmdf.lower()):
                print('Radar reports matching MDF')
                return

        # print('Current status after termination command:', _status.__dict__)
        if cnt * retrytime >= timeout:
            print(f'Measurement could not be started in ',
                  f'{cnt} seconds, use GUI')
            return

    # to ensure there is enough time for the radar to react
    time.sleep(2)


def scan_rhi(elevation_init,
             elevation_end,
             azimuth,
             **kwargs):
    mdffile = make_scan_mdf(elevation_init, elevation_end, azimuth, azimuth,
                            once=True,
                            **kwargs)
    return scan(mdffile, **kwargs)


def scan_ppi(elevation,
             **kwargs):
    azimuth_init, azimuth_end = 0 + NORTHOFFSET, 359.99 + NORTHOFFSET
    mdffile = make_scan_mdf(elevation, elevation, azimuth_init, azimuth_end,
                            once=True,
                            **kwargs)
    return scan(mdffile, **kwargs)


def scan_elevation(elevation_init,
                   elevation_end,
                   azimuth,
                   **kwargs):

    mdffiles = make_scan_mdf(elevation_init, elevation_end,
                             azimuth, azimuth, **kwargs)
    return scan(mdffiles, **kwargs)


def scan_azimuth(azimuth_init,
                 azimuth_end,
                 elevation,
                 **kwargs):
    mdffiles = make_scan_mdf(elevation, elevation,
                             azimuth_init, azimuth_end,
                             **kwargs)
    return scan(mdffiles, **kwargs)


def make_scan_mdf(elevation_init,
                  elevation_end,
                  azimuth_init,
                  azimuth_end,
                  # at which speed to scan
                  scanspeed=SCANSPEED,
                  # at which speed to move
                  fastspeed=FASTSPEED,
                  # this is the LOWER scantime, as it will be updated
                  # to match an even number of scans with the given speed/angle
                  duration=DURATION,
                  # the calibration interval (abs. cal.). be aware that once
                  # this is running the scan cannot be aborted
                  calibration_interval=1,
                  once=False,
                  # make a mdffile for each unique scanpattern to allow
                  # for easier postprocessing
                  seperatemdffiles=True,
                  # overwrite the basename in the beginning of the file
                  # TODO: Test if we can pass in \..\ or similar to get to
                  # another directory on the radar PC :-)
                  basename=None,
                  **kwargs):

    if (azimuth_init == azimuth_end or elevation_init == elevation_end):
        if azimuth_init == azimuth_end:
            # rhi like scan, movement in azi is fast
            movementtime = abs(90 - elevation_init) / scanspeed
            movementtime += abs(azimuth_init-NORTHOFFSET) / fastspeed
        elif elevation_init == elevation_end:
            # sector scan/ppi like scan, movement in elv is fast
            movementtime = abs(90 - elevation_init) / fastspeed
            movementtime += abs(azimuth_init - NORTHOFFSET) / scanspeed

        movementtime = int(np.ceil(movementtime))
        print(movementtime, '**')
    else:
        print('Scanning in both azimuth and elevation is not supported by',
              'this script. exiting....')
        return

    if azimuth_init == azimuth_end:
        onescanduration = (abs(elevation_end - elevation_init)/scanspeed)
        onescanduration = int(onescanduration)
    elif elevation_init == elevation_end:
        onescanduration = (abs(azimuth_end - azimuth_init)/scanspeed)
        onescanduration = int(onescanduration)
    else:
        print('Scanning in both azimuth and elevation is not supported by',
              'this script. exiting....')
        return

    if once:
        duration = onescanduration + movementtime
        nscans = 1
    else:
        nscans = duration / onescanduration
        nscans = int(np.ceil(nscans))
        # these have to be symmetrical, so always needs to be an even number
        if nscans % 2 != 0:
            print('Adding another scancycle to achieve even number of scans')
            nscans += 1

        duration = int(nscans * onescanduration) + movementtime

    if once:
        print(f'The scanrange of {elevation_init}° to {elevation_end}° with',
              f'a speed of {scanspeed} results in a duration of {duration} seconds',
              )

    else:
        if azimuth_init == azimuth_end:
            print(f'The scanrange of {elevation_init}° to {elevation_end}° with',
                  f'a speed of {scanspeed} results in',
                  f' {nscans} scans for {duration} seconds',
                  '(This may have been rounded up to create an even scan number)')
        elif elevation_init == elevation_end:
            print(f'The scanrange of {azimuth_init}° to {azimuth_end}° with',
                  f'a speed of {scanspeed} results in',
                  f' {nscans} scans for {duration} seconds',
                  '(This may have been rounded up to create an even scan number)')
    if azimuth_init == azimuth_end:
        mdffilename = 'SCAN_ELEVATION.MDF' if not once else 'SCAN_RHI.MDF'
        if basename is None:
            basename = 'ELEVATIONSCAN' if not once else 'RHISCAN'
        # elevation scan
        # the first scan going down
        SCAN_FORTH = Scan(elv=elevation_init,
                          azm=((azimuth_init-NORTHOFFSET)+360) % 360,
                          elv_target=elevation_end,
                          azm_target=((azimuth_init-NORTHOFFSET)+360) % 360,
                          elv_spd=scanspeed,
                          azm_spd=fastspeed,
                          )
        # the second scan (e.g. going back up)
        SCAN_BACK = Scan(elv=elevation_end,
                         azm=((azimuth_init-NORTHOFFSET)+360) % 360,
                         elv_target=elevation_init,
                         azm_target=((azimuth_init-NORTHOFFSET)+360) % 360,
                         elv_spd=scanspeed,
                         azm_spd=fastspeed,
                         )
    elif elevation_init == elevation_end:
        # maybe a bit of a misnomer but follows the CLOUDLAB nomenclature
        # from the miras
        mdffilename = 'SCAN_SECTOR.MDF' if not once else 'SCAN_PPI.MDF'
        if basename is None:
            basename = 'SECTORSCAN' if not once else 'PPISCAN'
        # azimuth/sector scan
        # the first scan going down
        SCAN_FORTH = Scan(elv=elevation_init,
                          azm=((azimuth_init-NORTHOFFSET)+360) % 360,
                          elv_target=elevation_init,
                          azm_target=((azimuth_end-NORTHOFFSET)+360) % 360,
                          elv_spd=fastspeed,
                          azm_spd=scanspeed,
                          )
        # the second scan (e.g. going back up)
        SCAN_BACK = Scan(elv=elevation_init,
                         azm=((azimuth_end-NORTHOFFSET)+360) % 360,
                         elv_target=elevation_init,
                         azm_target=((azimuth_init-NORTHOFFSET)+360) % 360,
                         elv_spd=fastspeed,
                         azm_spd=scanspeed,
                         )

    SCANS = [SCAN_FORTH, SCAN_BACK]
    # once means a RHI or PPI scan
    if once:
        SCANS = SCANS[:1]

    if once or seperatemdffiles:
        frames = [[0, 0, 1]]
    else:
        frames = [[0, 1, int(np.ceil(nscans/2))]]

    m = MeasDefFile()
    if seperatemdffiles:
        mdffiles = []

        for SCANNO, SCAN in enumerate(SCANS):
            _mdffilename = mdffilename.replace('.MDF', f'{SCANNO}.MDF')
            m.create(WORKDIR + _mdffilename,
                     CHIRPPRG,
                     SCAN,
                     frames=frames,
                     duration=onescanduration,
                     filelen=onescanduration,
                     cal_int=calibration_interval,
                     basename=basename,
                     )
            m.read(WORKDIR + _mdffilename)
            print(f'Made {WORKDIR+_mdffilename}:')
            m.output()
            mdffiles.append(WORKDIR + _mdffilename)
        # simply repeat the list entry of mdf files the
        # number of scans/2 so we can just use the same mdffiles again
        # and know how many times they should be made.
        mdffiles = mdffiles * int(np.ceil(nscans/2))
        return mdffiles
    else:
        m.create(WORKDIR + mdffilename,
                 CHIRPPRG,
                 SCANS,
                 frames=frames,
                 duration=duration,
                 filelen=onescanduration,
                 cal_int=calibration_interval,
                 basename=basename,
                 )
        m.read(WORKDIR + mdffilename)
        print(f'Made {WORKDIR+mdffilename}:')
        m.output()
        return WORKDIR + mdffilename


def scan(mdffile_or_list_of_mdffiles,
         reporting=True,
         reportinterval=5,
         quiet=True,
         dryrun=True,
         **kwargs):

    if isinstance(mdffile_or_list_of_mdffiles, str):
        mdffiles = [mdffile_or_list_of_mdffiles]
    else:
        mdffiles = mdffile_or_list_of_mdffiles

    m = MeasDefFile()

    if dryrun:
        for mdffile in mdffiles:
            m.read(mdffile)
            m.output()
        # os.remove(WORKDIR + f)
        return mdffiles
    else:
        try:
            client = Client(*CONFIG, SuppressOutput=quiet)
        except:
            print('Error connecting to data server, returning ...')
            print('Is the CLIENT running (on this computer).',
                  'We need the data server to forward commands ...')
            return

        radar_id = client.get_radar_id()
        radar_status = client.get_radar_status()
        if 'mdf_name' in radar_status.__dict__:
            oldmdf = radar_status.mdf_name
        else:
            oldmdf = None

        if isinstance(oldmdf, list):
            oldmdf = oldmdf[0]

        print(f'Radar is currently running {oldmdf}\n')
        try:
            # m.create(WORKDIR + f, CHIRPPRG, SCAN_FORTH, duration=duration)
            # made this way so that each scan of a mdflist has a
            # unique data file
            for mdfno, mdffile in enumerate(mdffiles):
                print(f'Running {mdffile}, {mdfno} of {len(mdffiles)}')
                m.read(mdffile)
                ensure_start(client, mdffile)
                if reporting:
                    report(client,
                           duration=m.Duration + 3,
                           reportfrequency=reportinterval)
                else:
                    time.sleep(m.Duration + 3)

                # client.terminate_radar_measurements()

            client.start_radar_measurements(oldmdf)
            # time.sleep(AFTERSCANWAIT)

        except KeyboardInterrupt:
            print('Stopping scanning operation manually...')
        finally:
            client.terminate_radar_measurements()

        print('Scan finished (see above if successful).')

        if oldmdf is not None:
            print(f'Installing previous MDF: {oldmdf}')
            # ensure_start(client, oldmdf)
            client.start_radar_measurements(oldmdf)

        return client


if __name__ == '__main__':
    pass
    # a half rhi at positioner 0° to avoid unneccessary movement for testing
    result = scan_elevation(90, 60,
                            NORTHOFFSET,
                            duration=20,
                            # dryrun=False,
                            dryrun=True,
                            quiet=True)

    result = scan_ppi(85,
                      # dryrun=False,
                      # dryrun=True,
                      quiet=False)

    # result = scan_rhi(10, 170,
    #                   NORTHOFFSET,
    #                   # dryrun=False,
    #                   dryrun=True,
    #                   quiet=True)

    # make some MBF file from all MDFs you have.
    # mbf = MeasBatchFile()
    # mdflist = [WORKDIR + i for i in os.listdir(WORKDIR) if 'MDF' in i]
    # mbf.create(WORKDIR+'test.mbf', mdflist, repetitions=3)
