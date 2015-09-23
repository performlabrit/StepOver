'''Classes for fetching and handling data from phasespace.'''

import collections
import logging
import OWL
import random
import threading
import time
import viz
import copy
import itertools

ERROR_MAP = {
    OWL.OWL_NO_ERROR: 'No Error',
    OWL.OWL_INVALID_VALUE: 'Invalid Value',
    OWL.OWL_INVALID_ENUM: 'Invalid Enum',
    OWL.OWL_INVALID_OPERATION: 'Invalid Operation',
}

class Error(Exception):
    pass

class OwlError(Error):
    def __init__(self, msg):
        self.msg = 'setting up {}'.format(msg)
        self.err = OWL.owlGetError()

    def __str__(self):
        return '{}: OWL error {} (0x{:04x})'.format(
            self.msg, ERROR_MAP.get(self.err, self.err), self.err)


Marker = collections.namedtuple('Marker', 'pos cond frame')
Pose = collections.namedtuple('Pose', 'pos quat cond frame')

class PointTracker(viz.EventClass):
    '''Track a set of markers on the phasespace server.
        self._raw_markers is the PS format set of markers
        self._markers is the vizard format set of markers
    '''

    def __init__(self, index, marker_ids):
        super(PointTracker, self).__init__()

        self.marker_ids = marker_ids
        self._index = index
        self._lock = threading.Lock()
        self._raw_markers = [Marker(pos=(0, 0, 0), cond=-1, frame = -1 ) for _ in marker_ids]
        self._markers = [Marker(pos=(0, 0, 0), cond=-1, frame = -1 ) for _ in marker_ids]
        self._targets = [None for _ in marker_ids]

        # schedule an update event for following marker data.
        def update(event):
            paired = None
            with self._lock:
                paired = zip(self._markers, self._targets)
            for marker, target in paired:
                if target is not None and 0 < marker.cond < 100:
                    target.setPosition(marker.pos)
                    #GD: Changed to vizard friendly position
                    #target.setPosition(-marker.pos[2],marker.pos[1],-marker.pos[0])
                    
        self.callback(viz.UPDATE_EVENT, update)

    def get_markers(self):
        '''Get a dictionary of all tracked markers.

        Returns
        -------
        {int: Marker} :
            A dictionary mapping phasespace marker ids to marker information.
        '''
        with self._lock:
            return dict(zip(self.marker_ids, self._markers))

    def get_marker(self, marker_id):
        '''Get a marker tuple for the current state of the given marker_id.

        Parameters
        ----------
        marker_id : int
            The phasespace marker id to get.

        Raises
        ------
        ValueError :
            If the given marker_id is not in this tracker.

        Returns
        -------
        Marker :
            A marker tuple with current location information. The marker tuple
            has .pos and .cond attributes.
        '''
        with self._lock:
            return self._markers[self.marker_ids.index(marker_id)]

    def update_markers(self, offset, marker, raw_marker):
        '''Update the state of the given marker for this tracker.

        This should really only be called by the Phasespace object.

        Parameters
        ----------
        offset : int
            The offset (within this tracker) of the marker to update.
        marker : Marker
            A marker tuple with updated location information.
        raw_marker : Marker
            A marker tuple with unscaled phasespace data.
        '''
        with self._lock:
            self._markers[offset] = marker
            self._raw_markers[offset] = raw_marker

    def link_marker(self, marker_id, target):
        '''Link an object to a particular marker for continual updates.

        Parameters
        ----------
        marker_id : int
            Phasespace ID of a marker to link.
        target : any
            An object to link to the given marker.

        Raises
        ------
        ValueError :
            If the given marker_id is not in this tracker.
        '''
        with self._lock:
            self._targets[self.marker_ids.index(marker_id)] = target


class RigidTracker(PointTracker):
    '''Track a rigid body on the phasespace server.'''
    
    #def __init__(self, index, center_marker_ids, localOffest_xyz):
    def __init__(self, index, marker_ids, center_marker_ids, localOffest_xyz):
        super(RigidTracker, self).__init__(index, marker_ids)
        
        self.center_marker_ids = center_marker_ids
        
        self._pose = Pose(pos=(0, 0, 0), quat=(1, 0, 0, 0), cond=-1, frame = -1)
        self._transform = viz.Transform()
        self._localOffset = [0,0,0]
        
        self.filepath = []
        self.filename = []
    
    def _loadPoseFromFile(self):
        ''' Set marker positions to positions contained in a specific *.rb file
        '''
        import os.path
        openfile = [];
        openfile = open( self.filepath + self.filename, 'r' );
        
        lineData = openfile.readlines();

        parsedData = [];

        markerID = [];
        markerPos = [];
        
        count = 0;
        
        for currentLine in lineData:
            
            tempLineDataList = currentLine.split(',');
            
            markerID.append( int(tempLineDataList[0]) );
            
            markerPos.append( map( float, tempLineDataList[1].split() ) );
            
            count += 1;
            
        #rof

        
        openfile.close()
        
        print 'Mocap: Read ' + str(count) + ' lines from the rigid body file.'
        if count == 0: print 'This is likely to cause OWL.init() to fail'
    
    
    def _getLocalPositions(self, psFormat = False):
        
        ''' 
        Returns markerPositions within a local frame of reference\
        Vizard format position
        Returns
        -------
        A list of tuples
        '''
        
        logging.info('Getting local marker positions %s', self.marker_ids)
        
        globalPositions = []
        localPositions = []
        com = []
        
        with self._lock:
            
            for mIdx in range(len(self.marker_ids)):

                if( psFormat == True ):
                    print 'Getting marker data in raw, PS format'
                    marker = self._raw_markers[mIdx]
                else:
                    marker = self._markers[mIdx]

                if marker is None or not 0 < marker.cond : #or not 0 < marker.cond < 100:
                    logging.error('missing marker %d for reset', mIdx)
                    print 'missing marker %d for reset'  %mIdx
                    return -1
                    
                globalPositions.append(marker.pos)

                if mIdx in self.center_marker_ids:
                    #print 'COM includes ' + str(mIdx)
                    # com = list of markers that define the center of mass
                    # (markers in self.center_marker_ids)
                    com.append(marker.pos)
        
        # compute center of mass
        cx = sum(x for x, _, _ in com) / len(com) 
        cy = sum(y for _, y, _ in com) / len(com)
        cz = sum(z for _, _, z in com) / len(com)
        logging.info('body center: (%s, %s, %s)', cx, cy, cz)
    

        # Construct marker_map, a dictionary of pos tuples
        # Keys = marker ID's
        # Values = XYZ in local coordinate space with an origin = to COM 
        
        localPositions_mIdx_xyz = []
        for i, (x, y, z) in enumerate(globalPositions):
            localPositions_mIdx_xyz.append((x - cx, y - cy, z - cz))
                
        return localPositions_mIdx_xyz 
        
    def get_pose(self):
        '''Return the current pose for our rigid body.

        Returns
        -------
        Pose :
            A pose tuple for our body. The pose tuple contains .pos, .quat, and
            .cond attributes.
        '''
        with self._lock:
            return self._pose

    def get_transform(self):
        
        '''Get a Vizard-compatible transform matrix for this rigid body.

        Returns
        -------
        matrix :
            A transform that can be applied to vizard objects.
        '''
        with self._lock:
            return self._transform
    
    def get_position(self):
        '''Get a Vizard-compatible position for this rigid body.

        Returns
        -------
        matrix :
            A transform that can be applied to vizard objects.
        '''
        
        with self._lock:
            return self._transform.getPosition()
    
    def get_euler(self):
        '''Get a Vizard-compatible position for this rigid body.

        Returns
        -------
        matrix :
            A transform that can be applied to vizard objects.
        '''

        with self._lock:
            return self._transform.getEuler()
            
    def link_position(self, target):
        '''Link an object's position to this rigid body for continual updates.

        Parameters
        ----------
        target : viz.Object
            An object to link to this rigid tracker.
        '''
        
        self.callback(
            viz.UPDATE_EVENT, lambda e: target.setPosition(self.get_position()))
    
    def link_euler(self, target):
        '''Link an object's position to this rigid body for continual updates.

        Parameters
        ----------
        target : viz.Object
            An object to link to this rigid tracker.
        '''
        
        self.callback(
            viz.UPDATE_EVENT, lambda e: target.setEuler(self.get_euler()))        
            
    def link_pose(self, target):
        '''Link an object to this rigid body for continual updates.

        Parameters
        ----------
        target : viz.Object
            An object to link to this rigid tracker.
        '''
        self.callback(
            viz.UPDATE_EVENT, lambda e: target.setMatrix(self.get_transform()))

    def update_pose(self, pose):
        '''Update the pose (and transform) for this rigid body.
        Note that self._localOffset is implemented here.
        This should really only be called by the Phasespace object.

        Parameters
        ----------
        pose : Pose
            The new pose information for this rigid body.
        '''
        with self._lock:
            self._pose = pose

            # update the vizard transform matrix. 
            # The pose has already been converted into the Vizard coordinate system
            self._transform.makeIdent()
            self._transform.setQuat(pose.quat)
            
            # Implement offset
            newPos = tuple(sum(t) for t in zip(pose.pos , tuple(self._localOffset) ) )
            
            self._transform.postTrans(newPos)
            
    def save(self):
        
        '''Save rigid body out to *.rb file
        '''
        
        fileObject = open(self.filepath + 'temp.rb','w')
        
        #localPositions = self._getLocalPositions()
                            
        # Get old marker id's and new positions
        oldRigidID_midx = self._getLocalPositions(psFormat = True)
        
        for idx in range(len(oldRigidID_midx)):
            posString = str(oldRigidID_midx[idx][0]) + ' ' + str(oldRigidID_midx[idx][1]) + ' ' + str(oldRigidID_midx[idx][2]);
            newLine = str(self.marker_ids[idx]) + ', ' + posString + '\n'
            fileObject.write(newLine);
            
        fileObject.close();
        
        #from shutil import move
        #move(self.filePath + 'temp.rb', self.filePath + self.fileName)

        from os import remove
        from shutil import move

        remove(self.filepath + self.filename)
        move(self.filepath + 'temp.rb', self.filepath + self.filename)

        print "Rigid body definition written to file"
         # reset phasespace marker positions
        
    def reset(self):
        
        '''Reset this rigid body based on the current locations of its markers.
        '''

        logging.info('resetting rigid body %s', self.marker_ids)

        localPositionsPS_mIdx_xyz = self._getLocalPositions( psFormat = True)
        
#        localPositionsPS_mIdx_xyz = []
#        for viz_XYZ in localPositionsViz_mIdx_xyz:
#            ps_XYZ = (-1000*viz_XYZ[2],1000*viz_XYZ[1],-1000*viz_XYZ[0])
#            localPositionsPS_mIdx_xyz.append(ps_XYZ)
                
        if (localPositionsPS_mIdx_xyz == -1):
            return
        
        OWL.owlTracker(self._index, OWL.OWL_DISABLE)
        
        for i, (x, y, z) in enumerate(localPositionsPS_mIdx_xyz):
        
            OWL.owlMarkerfv(OWL.MARKER(self._index, i),
                            OWL.OWL_SET_POSITION,
                            [x,y,z])
                            
        OWL.owlTracker(self._index, OWL.OWL_ENABLE)

class trackerBuffer(viz.EventClass):
    '''
    FIFO DEQUE BUFFER
    Append new data to the right of the deque
    
    '''
    def __init__(self,durationSecs = 10):
        
        self.bufferLength = 1000000 #durationSecs #* OWL.owlGetFloatv(OWL.OWL_FREQUENCY)[0]
        self.buffer_sIdx = collections.deque(maxlen=self.bufferLength) # a FIFO deque of tuples (time,[marker tracker list])

        self._lock = threading.Lock()

    def getSize(self):
        return len(self.buffer_sIdx)
        
    def append(self,timexTrackerList_tuple):
        
        with self._lock:
            self.buffer_sIdx.append( timexTrackerList_tuple )
    
    def popleft(self,timexTrackerList_tuple):
        
        with self._lock:
            self.buffer_sIdx.popleft();
            
    def getTrackers(self,lookBackDurationS):
        '''
        Use this function to get mocap data from past lookBackDurationS seconds

        Parameters
        ----------
        lookBackDurationS : int
            Seconds of buffered data to return
    
        Returns
        ------
        A list of tuples of form (frameNum, time,listOfTrackers)
        Newer values are on the right of the returned deque
        '''
        
        with self._lock:
            
            currentTime = time.time()
            #currentTime =  OWL.owlGetIntegerv(OWL.OWL_TIMESTAMP)
        
            timeSinceSample_fr = [currentTime - m[1] for m in self.buffer_sIdx ]
            
            #print str(timeSinceSample_fr )
            
            # find the first index smaller than bufferDurationS
            firstIndex = next(idx for idx, timePast in enumerate(timeSinceSample_fr) if timePast <= lookBackDurationS ) 
            
            #print 'TIME VALUES: = ' + str(timeSinceSample_fr[firstIndex:firstIndex+10])
            
            ## Plot the whole buffer GD
            #def plotYVal():
                # self.buffer_sIdx
                #print [sIdx[2][0].get_transform().getPosition()[1] for sIdx in trackerTuples_sIdx]
                #frame = [ s[2][1].get_marker(mIdx).frame for s in self.buffer_sIdx]
                #yVal = [ s[2][1].get_marker(mIdx).pos[1] for s in self.buffer_sIdx]
                

            ###
            # return new values
            # Note that you can't slice into deque without using isslice()        
            return collections.deque(itertools.islice(self.buffer_sIdx, firstIndex, len(self.buffer_sIdx)))
        
    def getMarkerPosition(self,markerID,trackerID,lookBackDurationS):
        '''
        Returns a list of tuples of form (timeStamp,XYZ)
        '''
                
        # passes back a list of tuples of form (frameNum, time,listOfTrackers) 
        # This list is just a slice of self.buffer_sIdx
        trackerTuples_sIdx = self.getTrackers(lookBackDurationS)
        
        # Get time and list of trackers for each sample
        #timeStamp_sIdx = [OWL.owlGetIntegerv(OWL.OWL_TIMESTAMP) - m[0] for m in trackerTuples_sIdx ]\
        #timeStamp_sIdx = [time.time() - sample[1] for sample in trackerTuples_sIdx ]
        
        # GD: Changed 8/11
        timeStamp_sIdx = [sample[1] for sample in trackerTuples_sIdx ]
        
        pos_sIdx = [sample[2][trackerID].get_marker(markerID).pos for sample in trackerTuples_sIdx]
        
        posBuffer_sIdx = []
        
        for sIdx in range(len(pos_sIdx)):
            posBuffer_sIdx.append((timeStamp_sIdx[sIdx],pos_sIdx[sIdx]))
            
        return posBuffer_sIdx[::-1]
        
    
    def psPositionToVizardPosition(self, x, y, z): # converts Phasespace pos to vizard cond
        return -sz * z + oz, sy * y + oy, -sx * x + ox
        
    def psQuatToVizardQuat(self, w, a, b, c): # converts Phasespace quat to vizard quat
        return -c, b, -a, -w
        
        pass
        
    def getRigidTransform(self,rigidIdx,lookBackDurationS):
        '''
        Returns the pose in Vizard format
        '''
        
        # passes back a list of tuples of form (frame, time,listOfTrackers) 
        # This list is just a slice of self.buffer_sIdx
        trackerTuples_sIdx = self.getTrackers(lookBackDurationS)
        
        # Get time and list of trackers for each sample
        #timeStamp_sIdx = [OWL.owlGetIntegerv(OWL.OWL_TIMESTAMP) - m[0] for m in trackerTuples_sIdx ]\
        
        # Time elapsed
        frame_sIdx = [m[0] for m in trackerTuples_sIdx ]
        timeStamp_sIdx = [m[1] for m in trackerTuples_sIdx ]
        
        trackers_sIdx_tIdx = [m[2] for m in trackerTuples_sIdx ]
        
        tformBuffer_sIdx = []
        
        # GD: DEBUG!  THIS DATA DOES NOT CHANGE MUCH OVER TIME
        # print [m[2].getPosition()[1] for m in tformBuffer_sIdx]
        # Print first rigid body height
        # print [sIdx[2][0].get_transform().getPosition()[1] for sIdx in trackerTuples_sIdx]
        
        # Iterate through each sample.
        # ...remember that each sample stores a list of trackers
        for sIdx, sample_tIdx in enumerate(trackers_sIdx_tIdx):
            
            ### Keyerror
            try:
                tformBuffer_sIdx.append( (frame_sIdx[sIdx],timeStamp_sIdx[sIdx], trackers_sIdx_tIdx[sIdx][rigidIdx].get_transform()))
            except KeyError, e:
                # Bad indexing.
                print 'Rigid index invalid for at least one of the trackers stored in the buffer'
                return

        return tformBuffer_sIdx
        
        #return tformBuffer_sIdx[::-1] # reverse the list so that most recent entries are last
        
class phasespaceInterface(viz.EventClass):
    '''Handle the details of getting mocap data from phasespace.

    Parameters
    ----------
    self.serverAddress : str
        The hostname for the phasespace server.
    self.owlParamFrequ : float
        Poll phasespace this many times per second. Defaults to 100.
    scale : (float, float, float)
        Scale raw phasespace position data by this amount. The default is to
        scale positions by 0.001, thus converting from mm to meters.
    offset : (float, float, float)
        Translate scaled phasespace position data by this amount.
    postprocess : bool
        Enable phasespace postprocessing. The default is no postprocessing.
    slave : bool
        Run our OWL client in slave mode. The default is to run OWL in master mode.
    '''

    UPDATE_TIMER = 0
    
    def __init__(self, config = None):
        
        super(phasespaceInterface, self).__init__()
    
        #self.trackPosBuff_sIdx_mIdx_XYZ = collections.deque(maxlen=200) # a deque of tuples (time,[marker tracker list])
        
        self.config = config
        self.writer = []
        self.isWriting = False
        
        self.startTime = time.time()
        
        if config==None:
            
            print('***Debug mode***')
            self.phaseSpaceFilePath = '../Resources/'
            self.origin 	= [0,0,0];
            self.scale 		= [0.001,0.001,0.001];
            self.serverAddress = '192.168.1.230';
            
            self.rigidFileNames_ridx= ['shutterGlass.rb']
            self.rigidAvgMarkerList_rIdx_mId = [[3,4]]
            self.rigidOffsetMM_ridx_WorldXYZ = [[0,0,0],[0,0,0]]
                        
            self.owlParamMarkerCount = 10
            self.owlParamFrequ = OWL.OWL_MAX_FREQUENCY
            self.owlParamInterp = 0
            self.owlParamMarkerCondThresh = 50
            self.owlParamPostProcess = 0
            
            self.owlParamModeNum = 1
            print '**** Using default MODE #' + str(self.owlParamModeNum) + ' ****'
            
        else:
            
            self.phaseSpaceFilePath 	= './Resources/'
            self.origin 				= self.config['phasespace']['origin']
            self.scale 					= self.config['phasespace']['scale']
            self.serverAddress 			= self.config['phasespace']['phaseSpaceIP']
            self.rigidFileNames_ridx	= self.config['phasespace']['rigidBodyList']

            self.rigidOffsetMM_ridx_WorldXYZ = eval(self.config['phasespace']['rigidOffsetMM_ridx_WorldXYZ'])
            self.rigidAvgMarkerList_rIdx_mId = eval(self.config['phasespace']['rigidAvgMarkerList_rIdx_mId'])
            
            self.owlParamModeNum	= self.config['phasespace']['owlParamModeNum']
            
            self.owlParamMarkerCount = self.config['phasespace']['owlParamMarkerCount']
            self.owlParamFrequ = self.config['phasespace']['owlParamFrequ'] 
            self.owlParamInterp = self.config['phasespace']['owlParamInterp']
            self.owlParamMarkerCondThresh = self.config['phasespace']['owlParamMarkerCondThresh']
            self.owlParamRigidCondThresh = self.config['phasespace']['owlParamRigidCondThresh']
            self.owlParamPostProcess = self.config['phasespace']['owlParamPostProcess']
        
        # set default frequency
        if( self.owlParamFrequ == 0 ):			
            self.owlParamFrequ = OWL.OWL_MAX_FREQUENCY;
        
        flags = 'OWL.OWL_MODE' + str(self.owlParamModeNum)
        
        if( self.owlParamPostProcess ):
            flags = flags + '|OWL.OWL_POSTPROCESS'
        
    
        initCode = OWL.owlInit(self.serverAddress,eval(flags))
        #initCode = owlInit(self.serverAddress,0)
        
        if (initCode < 0): 
            raise OwlError('phasespace')
            print "Mocap: Could not connect to OWL Server"
            exit()
        else:
            print '**** OWL Initialized with flags: ' + flags + ' ****'
        
        OWL.owlSetFloat(OWL.OWL_FREQUENCY, self.owlParamFrequ)
        OWL.owlSetInteger(OWL.OWL_STREAMING, OWL.OWL_ENABLE)
        OWL.owlSetInteger(OWL.OWL_INTERPOLATION, self.owlParamInterp)
        OWL.owlSetInteger(OWL.OWL_TIMESTAMP, OWL.OWL_ENABLE)
        
        self.markerTrackerBuffer = trackerBuffer()
        
        self.trackers = []
        
        ######################################################################
        ######################################################################
        # Create rigid objects
        
        # for all rigid bodies passed into the init function...
        for rigidIdx in range(len(self.rigidFileNames_ridx)):
            
            rigidOffsetMM_WorldXYZ  = [0,0,0]
            rigidAvgMarkerList_mIdx   = [0]
            
            if( len(self.rigidOffsetMM_ridx_WorldXYZ) < rigidIdx ):
                print 'Rigid offset not set! Using offset of [0,0,0]'
            else:
                rigidOffsetMM_WorldXYZ = self.rigidOffsetMM_ridx_WorldXYZ[rigidIdx]
            
            if( len(self.rigidAvgMarkerList_rIdx_mId) < rigidIdx ):
                print 'Average markers not provided! Using default (marker 0)'
            else:
                rigidAvgMarkerList_mIdx  = self.rigidAvgMarkerList_rIdx_mId[rigidIdx]
          
            self.track_rigid(self.rigidFileNames_ridx[rigidIdx],rigidAvgMarkerList_mIdx, rigidOffsetMM_WorldXYZ)
            # def __init__(self, index, marker_ids, center_marker_ids, localOffest_xyz):
        
        markersFromRigids = self.get_markers()
        
        if( self.owlParamMarkerCount > len(markersFromRigids) ):
            
            markersToTrack = list( set(range(self.owlParamMarkerCount)) - set(markersFromRigids.keys())  )            
            self.track_points( markersToTrack  )
    
        
        ###########################################################################
        
        self._updated = viz.tick()
        self._thread = None
        self._running = False
        
    def __del__(self):
        '''Clean up our connection to the phasespace server.'''
        OWL.owlDone()

    def start_thread(self):
        self._running = True
        self._thread = threading.Thread(target=self.update_thread)
        self._thread.start()
        self.callback(viz.EXIT_EVENT, self.stop_thread)

    def stop_thread(self):

        if self.isWriting:
            # This closes the text file and joins the thread
            self.writer.stop_thread()
        
        self._running = False
        if self._thread:
            self._thread.join()
            self._thread = None

    def update_thread(self):
        while self._running:
            self.update()
            elapsed = viz.tick() - self._updated
            wait = 1. / self.owlParamFrequ - elapsed
            while wait < 0:
                wait += 1. / self.owlParamFrequ
            #time.sleep(wait)

    def start_timer(self):
        self.callback(viz.TIMER_EVENT, self.update_timer)
        self.starttimer(Phasespace.UPDATE_TIMER, 0, viz.FOREVER)

    def update_timer(self, timer_id):
        if timer_id == Phasespace.UPDATE_TIMER:
            self.update()

    def update(self):
        
        '''Update our knowledge of the current data from phasespace.'''
        now = viz.tick()
        #logging.info('%dus elapsed since last phasespace update',
        #             1000000 * (now - self._updated))
        self._updated = now

        frameNum = OWL.owlGetIntegerv(OWL.OWL_FRAME_NUMBER)[0]
        
        rigids = OWL.owlGetRigids()
        markers = OWL.owlGetMarkers()
        
        err = OWL.owlGetError()
        if err != OWL.OWL_NO_ERROR:
            hex = '0x%x' % err
            logging.debug(
                'OWL error %s (%s) getting marker data',
                ERROR_MAP.get(err, hex), hex)
            return

        sx, sy, sz = self.scale
        ox, oy, oz = self.origin
        
        def psPositionToVizardPosition(x, y, z): # converts Phasespace pos to vizard cond
            #return sz * z + oz, sy * y + oy, sx * x + ox
            return -sz * z + oz, sy * y + oy, -sx * x + ox
        
        def psQuatToVizardQuat(w, a, b, c): # converts Phasespace quat to vizard quat
            return -c, b, -a, -w

        #trackerPos_tIdx_XYZ = [0] * (len(markers) + len(rigids))
        
        for marker in markers:
            if( marker.cond > 0 and marker.cond < self.owlParamMarkerCondThresh ):
              
                t, o = marker.id >> 12, marker.id & 0xfff
                x, y, z = marker.x, marker.y, marker.z
                
                vizPos = psPositionToVizardPosition(x, y, z)
                
                self.trackers[t].update_markers(o,
                    Marker(pos=vizPos, cond=marker.cond, frame = marker.frame),
                    Marker(pos=(x, y, z), cond=marker.cond, frame = marker.frame))
                
        for rigid in rigids:
            if( rigid.cond > 0 and rigid.cond < self.owlParamMarkerCondThresh ):
                
                vizPos = psPositionToVizardPosition(*rigid.pose[0:3])

                self.trackers[rigid.id].update_pose(Pose(
                    vizPos,
                    quat=psQuatToVizardQuat(*rigid.pose[3:7]),
                    cond=rigid.cond,
                    frame = rigid.frame))
                
                #print self.markerTrackerBuffer.buffer_sIdx[-1][0]

                # get frame of last marker
                try:
                    lastFrame = mocap.markerTrackerBuffer.buffer_sIdx[-1][2][0]._pose.frame
                    print 'This - Last: ' + str( rigid.frame) + ' ' + str(lastFrame)
                except:
                    pass
            
        # Is this fresh data?
        try:
            lastRigidFrame = mocap.markerTrackerBuffer.buffer_sIdx[-1][2][0]._pose.frame
            
            if( self.markerTrackerBuffer.getSize() == 0 or 
                lastRigidFrame != frameNum ): 
                    
                #self.markerTrackerBuffer.buffer_sIdx[-1][0] != frameNum ): 
                
                #print 'FrameNum: ' + str(frameNum) + ' ' + str(self.markerTrackerBuffer.buffer_sIdx[-1].frame)
                
                # Yes!  Store it in the buffer.
                self.markerTrackerBuffer.append((frameNum,time.time(),self.trackers))
        except:
            pass
            
    
    def track_points(self, markers):
        '''Track a set of markers using phasespace.

        Parameters
        ----------
        markers : int or sequence of int
            If this is an integer, specifies the number of markers we ought to
            track. If this is a sequence of integers, it specifies the IDs of
            the markers to track.

        Returns
        -------
        PointTracker :
            A PointTracker instance to use for tracking the markers in question.
        '''
        if isinstance(markers, int):
            markers = range(markers)
        marker_ids = sorted(markers)

        # set up tracker using owl libraries.
        index = len(self.trackers)
        OWL.owlTrackeri(index, OWL.OWL_CREATE, OWL.OWL_POINT_TRACKER)
        for i, marker_id in enumerate(marker_ids):
            OWL.owlMarkeri(OWL.MARKER(index, i), OWL.OWL_SET_LED, marker_id)
        OWL.owlTracker(index, OWL.OWL_ENABLE)
        if OWL.owlGetStatus() == 0:
            raise OwlError('point tracker (index {})'.format(index))

        tracker = PointTracker(index, marker_ids)
        self.trackers.append(tracker)
        return tracker

   
    def get_markers(self):
        '''Get a dictionary of all current marker locations.

        Returns
        -------
        dict :
            A dictionary that maps phasespace marker ids to Marker tuples.
        '''
        markers = {}
        for tracker in self.trackers:
            markers.update(tracker.get_markers())
            
        return markers
    
    def get_MarkerPos(self,markerIdx,bufferDurationS = None):

        ''' Returns marker position in vizard format
        buffer duration will return the number of samples S seconds to have been collected over the previous S seconds
        '''
        
        if( bufferDurationS ):
            
            tracker, trackerIdx = self.get_MarkerTracker(markerIdx)
            return self.markerTrackerBuffer.getMarkerPosition(markerIdx,trackerIdx,bufferDurationS)
            
        else:

            markerTrackers_mIdx = self.get_markers()
            
            try:
                return markerTrackers_mIdx[markerIdx].pos
            except:
                print 'Marker index not valid.  Either marker not yet seen, or not in profile'
                
    def getMarkerPosition(self,markerIdx,bufferDurationS = None):
        ''' Included for backwards compatability
        '''
        return self.get_MarkerPos(markerIdx,bufferDurationS)
            
    def get_MarkerTracker(self,markerIdx):
        
        ''' Included for backwards compatability
        GD FIXME:  Returns marker object, not a tracker object
        should search through trackers until it finds the point tracker that contains the marker ID
        Then, it should return the pointtracker object
        '''
        #markerTrackers_mIdx = self.get_markers()
        #return markerTrackers_mIdx[markerIdx]
        
        for tIdx , tracker in enumerate(self.trackers):
                
            if( markerIdx in tracker.marker_ids ):
                    
                    return tracker, tIdx
                
        print 'get_MarkerTracker: Could not find marker ' + str(markerIdx) + ' in trackers.'
    
    def linkToMarker(self,markerIdx,targetNode3D):

        self.get_MarkerTracker(markerIdx).link_marker(markerIdx,targetNode3D)
        
    def get_MarkerCond(self,markerIdx):
        '''Returns marker condition
        
        '''            
        markerTrackers_mIdx = self.get_markers()
        return markerTrackers_mIdx[markerIdx].cond
        

    def track_rigid(self, markers_orFilename=None, center_markers=None, localOffest_xyz = [0,0,0]):
        '''Add a rigid-body tracker to the phasespace workload.

        Parameters
        ----------
        markers_orFilename : varied
            This parameter describes the markers that make up the rigid body. It
            can take several forms:

            - An integer, n. This will result in tracking markers 0 through n-1.
            - A sequence of integers, (n1, n2, ...). This will use markers n1,
              n2, ... to track the rigid body.
            - A dictionary, {n1: (x, y, z), n2: ...}. This will use markers n1,
              n2, ... to track the rigid body, using relative marker offsets
              specified by the values in the dictionary.
            - A string. The rigid body configuration will be loaded from the
              file named in the string.

            If markers_orFilename is an integer or sequence of integers, then random marker
            offsets will be assigned initially; call the .reset() method on the
            rigid tracker to reassign the marker offsets.

        center_markers : sequence of int
            This parameter specifies which marker ids to use for computing the
            center of the rigid body. If this is None, all markers will be
            used.

        Returns
        -------
        RigidTracker :
            A RigidTracker instance to use for tracking this rigid body.
        '''
        def random_offsets():
            return [random.random() - 0.5 for _ in range(3)]

        marker_map = {}

        # If markers_orFilename is a dictionary
        if isinstance(markers_orFilename, dict):
            marker_map = markers_orFilename

        # If markers_orFilename is an int
        if isinstance(markers_orFilename, int):
            for i in range(markers_orFilename):
                marker_map[i] = random_offsets()

        # If markers_orFilename is a tuple
        if isinstance(markers_orFilename, (tuple, list, set)):
            for i in markers_orFilename:
                marker_map[i] = random_offsets()
        
        # If markers_orFilename is a string
        if isinstance(markers_orFilename, str):
            
            fileLocation = self.phaseSpaceFilePath + markers_orFilename
            print "Initializing rigid body: " + fileLocation 
            
            import os
            
            #import os.path
            #f = open(os.path.dirname(__file__) + '/../data.yml')

            # load rigid body configuration from a file.
            with open(fileLocation) as handle:
                for line in handle:
                    id, x, y, z = line.replace(',', '').strip().split()
                    marker_map[int(id)] = float(x), float(y), float(z)
                    
        marker_map = sorted(marker_map.iteritems())
        marker_ids = tuple(i for i, _ in marker_map)

        # set up tracker using owl libraries.
        # Marker locations have been read in from file
        index = len(self.trackers)

        OWL.owlTrackeri(index, OWL.OWL_CREATE, OWL.OWL_RIGID_TRACKER)

        for i, (marker_id, pos) in enumerate(marker_map):
            OWL.owlMarkeri(OWL.MARKER(index, i), OWL.OWL_SET_LED, marker_id)
            OWL.owlMarkerfv(OWL.MARKER(index, i), OWL.OWL_SET_POSITION, pos)
            
        OWL.owlTracker(index, OWL.OWL_ENABLE)
        if OWL.owlGetStatus() == 0:
            raise OwlError('rigid tracker (index {})'.format(index))
        
        tracker = RigidTracker(index,marker_ids, center_markers or marker_ids, localOffest_xyz)

        if isinstance(markers_orFilename, str):
            tracker.filepath = self.phaseSpaceFilePath
            tracker.filename = markers_orFilename
            
        self.trackers.append(tracker)
        return tracker

    def returnPointerToRigid(self,fileName):
        ''' Included for backwards compatability
        '''
        return self.get_rigidTracker(fileName)
        
    def get_rigidIdx(self, fileName):

        for tIdx , tracker in enumerate(self.trackers):
            
            if( isinstance(tracker, RigidTracker) and tracker.filename.find(fileName)>-1 ):
                    return tIdx
                
        print 'returnPointerToRigid: Could not find ' + fileName
        
    def get_rigidTracker(self,fileName):
        '''
        Accepts a partial filenames, such as 'hmd' or 'paddle'
        Will return a pointer to ta rigidTracker
        This tracker is the first rigid body that contains this string
        '''
        
        return self.trackers[self.get_rigidIdx(fileName)]
    
    def getRigidTransform(self,fileName,bufferDurationS = None):

        rIdx = self.get_rigidIdx(fileName)
        
        if( bufferDurationS ):
            return self.markerTrackerBuffer.getRigidTransform(rIdx,bufferDurationS)
        else:
            
            return self.trackers[rIdx].get_transform()

    def resetRigid( self, fileName ):
        '''Finds the rigid body corresponding to this filename.
        Resets marker positions based upon current position
        '''
        
        rigidBody = self.get_rigidTracker( fileName );
        
        if( rigidBody ):
            
            #if( self.mainViewUpdateAction ):
            rigidBody.reset()
        else:
            
            print ('Error: Rigid body not initialized');
            
        #fi
        
    #fed
        
    def saveRigid(self,fileName):
        '''Finds the rigid body corresponding to this filename.
        Saves marker positions out to *.rb file
        '''
        
        rigidBody = self.get_rigidTracker(fileName)
        
        if(rigidBody):
            rigidBody.save()
        else: print 'Error: Rigid body not initialized'
    
    def setBufferLength(self,durationSecs):

        self.markerTrackerBuffer =  trackerBuffer(durationSecs)

        #self.toggleUpdateWithMarker()
    
    def createOutputFile(self,fileObj):
        
        self.isWriting = True
        self.writer = dataWriter(self,fileObj)
        self.writer.rigidsToBeWritten_rIdx = self.rigidFileNames_ridx
  
    
#    def showMarkers(self):
#        
#        
#        class mocapMarkerSphere(visObj):
#            def __init__(self,mocap,room,markerNum):
#                #super(visObj,self).__init__(room,'sphere',.04,[0,0,0],[.5,0,0],1)
#
#                position = [0,0,0]
#                shape = 'sphere'
#                color=[.5,0,0]
#                size = [.015]
#                
#                visObj.__init__(self,room,shape,size,position,color)
#                
#                #self.physNode.enableMovement()
#                self.markerNumber = markerNum
#                self.mocapDevice = mocap
#                mocap.linkToMarker(markerNum,self.node3D)
#
#        markerSphere_mIdx = []
#        
#        for mIdx in range(len( experimentObject.config.mocap.owlParamMarkerCount)):
#            markerSphere_mIdx.append( mocapMarkerSphere(experimentObject.config.mocap, experimentObject.room, mIdx) )


class dataWriter(viz.EventClass):	
    def __init__(self,mocap,fileObj):

        viz.EventClass.__init__(self)

        self.lineBuffer = collections.deque()
        self._lock = threading.Lock()
        self.fileObj = fileObj

        self.mocap = mocap
        
        self._updated = viz.tick()
        self._thread = None
        self._running = False	

        # This class will write out any data newer than self.writeTime 
        self.writeDataFromTime = 0        
        
        self.isWriting = 0

        self.rigidsToBeWritten_rIdx = []
        
        self.start_thread()

    def write(self,lineData):
        '''
        This adds text to a buffer which is written out by 
        writeFromLineBuffer - the threaded function
        '''
        with self._lock:
            # append line to start of line buffer
            self.lineBuffer.appendleft(lineData)

    def start_thread(self):
        
        self._running = True
        self._thread = threading.Thread(target=self.update_thread)
        self._thread.start()
        self.callback(viz.EXIT_EVENT, self.stop_thread)

    def stop_thread(self):
        
        self._running = False
        
        if self._thread:

            self._thread.join()
            self._thread = None
            
            self.fileObj.flush()
            self.fileObj.close()

    def update_thread(self):

        while self._running:
            
            # This is where text data is gathered, formatted into a string, and appended to the writeOutBuffer
            if( self.writeDataFromTime > 0):
                
                self.isWriting = 1
                t1 = time.time()

                for rIdx in self.rigidsToBeWritten_rIdx:
                    self.write( self.formatRigidData(rIdx) + self.formatMarkerData(rIdx))
                
                self.write('\n') # One big line per trial
                
                self.writeDataFromTime = 0
                
                print 'Reading took ' + str(time.time() - t1)
                
            t2 = time.time()
            # This is where text data is written to file
            
            if( len(self.lineBuffer) > 0 ):
                self.writeFromBuffer()
                
            if( self.isWriting == 1 and len(self.lineBuffer) == 0 ):
                print 'Writing took ' + str(time.time() - t2)
                self.isWriting = 0
                
            elapsed = viz.tick() - self._updated
    
    def writeFromBuffer(self):
        
        with self._lock:
            for idx in range(len(self.lineBuffer)):
                # write out last (oldest) entry
                self.fileObj.write(self.lineBuffer[-1])
                self.lineBuffer.pop()
    
    
    def formatMarkerData(self,rbFilename):
    # rigid body marker data
        
        mPositionOutString = ''

        rb = self.mocap.returnPointerToRigid(rbFilename)

        markerID_mIdx = rb.marker_ids
        
        for mID in markerID_mIdx:
            
            # Returns a list of tuples of the form (time,ListOfMarkerXYZ)
            #markerPosBuffer_sIdx_XYZ = [mocap.getMarkerPosition(mID,timeElapsed) for mID in markerID_mIdx]
            timeElapsed = time.time() - self.writeDataFromTime
            markerPosBuffer_sIdx_XYZ = self.mocap.getMarkerPosition(mID,timeElapsed)
            
            # Write the line header
            # e.g. '<< rigidVarName-M0_xyz 3 '
            mPositionOutString = mPositionOutString + '<< ' + rbFilename + '-M' + str(mID) +'_XYZ ' + str(len(markerPosBuffer_sIdx_XYZ)) + ' '
            
            # Iterate through samples (sIdx) and get data
            for m in markerPosBuffer_sIdx_XYZ:
                
                timeStamp = m[0]
                pos_XYZ = m[1]
                
                mPositionOutString = mPositionOutString + '[ %f %f %f %f ] ' % (timeStamp, pos_XYZ[0], pos_XYZ[1], pos_XYZ[2])
                
            mPositionOutString = mPositionOutString  + '>> '
        

        return mPositionOutString
        
    def formatRigidData(self,rbFilename):

        # rigid body position and quaternion (rotation) data
        timeElapsed = time.time() - self.writeDataFromTime
        tformBuffer_sIdx = self.mocap.getRigidTransform(rbFilename,timeElapsed)
        
        # Output is of format << Varname NumEntries [A B C] >>
        # eg << glassesRb_quatXYZW 3 [timeStamp x1 y1 z1 w1] [timeStamp x2 y2 z2 w2] [timeStamp x3 y3 z3 w3] >>
        
        tformOutString = '<< ' + rbFilename + '_quatXYZW ' + str(len(tformBuffer_sIdx)) + ' '
        posOutString = '<< ' + rbFilename + '_posXYZ ' + str(len(tformBuffer_sIdx)) + ' '
        
        # Build two seperate strings 
        for m in tformBuffer_sIdx:
        
            timeStamp = m[0]
            quat_XYZW = m[1].getQuat()
            
            tformOutString = tformOutString  + '[ %f %f %f %f %f ] ' % (timeStamp, quat_XYZW[0], quat_XYZW[1], quat_XYZW[2], quat_XYZW[3])
            
            pos_XYZ = m[1].getPosition()
            posOutString = posOutString  + '[ %f %f %f %f ] ' % (timeStamp, pos_XYZ[0], pos_XYZ[1], pos_XYZ[2])
        
        tformOutString = tformOutString  + '>> '
        posOutString = posOutString  + '>> '
        
        #self.writer.write(tformOutString + posOutString)
        
        return tformOutString + posOutString
    
    
if __name__ == "__main__":
  
  
    mocap = phasespaceInterface();
    mocap.start_thread()
    
    #import vizshape
    #vizshape.addGrid()
    
    piazza = viz.addChild('piazza.osgb')
    viz.window.setFullscreenMonitor(2)
    viz.go(viz.FULLSCREEN)
    
    viz.clearcolor(viz.BLACK)
    
    #######
    
    sg = mocap.returnPointerToRigid('shutter')
    
    import vizshape    
    sgSphere = vizshape.addSphere(radius = 0.02)

    # First, link visual to rigid body
    sg.link_pose(sgSphere)

    #######
    
    import matplotlib
    matplotlib.use('agg') 
    import matplotlib.pyplot as plt
        
    import vizmatplot
    
    plotDur = 100
    
    ###---matplotlib codes---####
    fig = plt.figure()	#instantiate pyplot figure
    ax_height = fig.add_subplot(111)	#create axes
    ax_height.axis([-plotDur*2,0,-1,2])	#determine axis limits
    
    
    pos_fr = []
    time_fr = []
    
    for i in range(0,100000):
        time_fr.append(0)
        pos_fr.append(0)
    
    line_height, = ax_height.plot(time_fr,pos_fr, 'r')	#instantiate plot
    matplot = vizmatplot.Show(fig)
    plt.hold(True)
    
    matplot = vizmatplot.Show(fig)
         
    def plotRigidPos(plotDur):
        
        currentTime = time.time()
        
        tformBuffer_sIdx = mocap.getRigidTransform('shutter',plotDur )
        #print str(currentTime) + ' First: ' + str(tformBuffer_sIdx[0][0]) + ' Last: ' + str(tformBuffer_sIdx[-1][0])
        
        frame_fr = [m[0] for m in tformBuffer_sIdx]
        time_fr = [-(currentTime - m[1]) for m in tformBuffer_sIdx]
        pos_fr = [m[2].getPosition()[1] for m in tformBuffer_sIdx]
        
        #print pos_fr

        line_height.set_data(time_fr,pos_fr)
    
    def plotMarkerPos(mIdx,plotDur):
        
        currentTime = time.time()
        # gets tuples in the form of timeStamp, XYZ
        markerBuffer_sIdx = mocap.getMarkerPosition(mIdx,plotDur )
    
        
        #frame_fr = [m[0] for m in markerBuffer_sIdx]
        time_fr = [-(currentTime - m[0]) for m in markerBuffer_sIdx]
        pos_fr = [m[1][1] for m in markerBuffer_sIdx]
        
        #print pos_fr

        line_height.set_data(time_fr,pos_fr)
        
        
#        posOutString = ''
        
#        # Build two seperate strings 
#        for m in tformBuffer_sIdx:
#        
#            timeStamp = currentTime-m[0]
#            quat_XYZW = m[1].getQuat()
#            
#            pos_XYZ = m[1].getPosition()
#            #posOutString = posOutString  + '[ %f %f %f %f ] ' % (timeStamp, pos_XYZ[0], pos_XYZ[1], pos_XYZ[2])
#            posOutString = posOutString  + '[ %f - %f ] ' % (timeStamp, pos_XYZ[1])
#
#        print posOutString
        

    
    import vizact
    # vizact.onkeydown('p',plotRigidPos,plotDur)
    vizact.ontimer(0.25,plotRigidPos,plotDur)
    # vizact.ontimer(0.25,plotMarkerPos,2,plotDur)