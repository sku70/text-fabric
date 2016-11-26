import os,sys,array,pickle,json,gzip,collections,time
from datetime import datetime
from .timestamp import Timestamp
from .helpers import *

ERROR_CUTOFF = 20
GZIP_LEVEL = 2
PICKLE_PROTOCOL = 4

SKELETON = (
    'otype',
    'monads',
)

class Data(object):
    def __init__(self, path, edgeValues=False, data=None, isEdge=None, metaData={}, method=None, dependencies=None):
        (dirName, baseName) = os.path.split(path)
        (fileName, extension) = os.path.splitext(baseName)
        self.path = path
        self.dirName = dirName
        self.fileName = fileName
        self.extension = extension
        self.binDir = '{}/.tf'.format(dirName)
        self.binPath = '{}/{}.tfx'.format(self.binDir, self.fileName)
        self.edgeValues = edgeValues
        self.isEdge = isEdge
        self.metaData = metaData
        self.method = method
        self.dependencies = dependencies
        self.data = data
        self.dataLoaded = False
        self.dataError = False

    def load(self):
        self.tm = Timestamp(level=1)
        origTime = self._getModified()
        binTime = self._getModified(bin=True)
        sourceRep = ', '.join(dep.fileName for dep in self.dependencies) if self.method else self.path
        msgFormat = '{:<1} {:<20} from {}\n'
        actionRep = ''
        good = True

        if self.dataError:
            actionRep = 'E' # there has been an error in an earlier computation/compiling/loading of this feature
            good = False
        elif self.dataLoaded and (not origTime or self.dataLoaded >= origTime) and (not binTime or self.dataLoaded >= binTime):
            actionRep = '=' # loaded and up to date
        elif not origTime and not binTime:
            actionRep = 'X' # no source and no binary present
            good = False
        else:
            if not origTime:
                actionRep = 'b'
                good = self._readDataBin()
            elif not binTime or origTime > binTime:
                actionRep = 'C' if self.method else 'T'
                good = self._compute() if self.method else self._readTf()
                if good: self._writeDataBin()
            else:
                actionRep = 'B'
                good = True if self.method else self._readTf(metaOnly=True)
                if good: good = self._readDataBin()
        if good:
            self.dataLoaded = time.time() 
            if actionRep != '=':
                self.tm.info(msgFormat.format(actionRep, self.fileName, sourceRep))
        else:
            self.dataError = True
            self.tm.error(msgFormat.format(actionRep, self.fileName, sourceRep))
        return good

    def unload(self):
        self.data = None
        self.dataLoaded = False

    def _readTf(self, metaOnly=False):
        path = self.path
        if not os.path.exists(path):
            self.tm.error('TF reading: feature file "{}" does not exist\n'.format(path))
            return False
        fh = open(path)
        i = 0
        self.metaData = {}
        for line in fh:
            i += 1
            if i == 1:
                text = line.rstrip()
                if text == '@edge': self.isEdge = True
                elif text == '@node': self.isEdge = False
                else:
                    self.tm.error('Line {}: missing @node/@edge\n'.format(i))
                    fh.close()
                    return False
                continue
            text = line.rstrip('\n')
            if len(text) and text[0] == '@':
                fields = text.rstrip()[1:].split('=', 1)
                self.metaData[fields[0]] = fields[1] if len(fields) == 2 else None
                continue
            else:
                if text != '':
                    self.tm.error('Line {}: missing blank line after metadata\n'.format(i))
                    fh.close()
                    return False
                else:
                    break
        good = True
        if not metaOnly:
            good = self._readDataTf(fh, i)
        fh.close()
        return good
        
    def _readDataTf(self, fh, firstI):
        errors=collections.defaultdict(list)
        first = True
        i = firstI
        implicit_node = 0
        data = {}
        isEdge = self.isEdge
        edgeValues = self.edgeValues
        normFields = 3 if isEdge and edgeValues else 2
        for line in fh:
            i += 1
            fields = line.rstrip('\n').split('\t')
            lfields = len(fields)
            if lfields > normFields: 
                errors['wrongFields'].append(i)
                continue
            if lfields == normFields:
                nodes = setFromSpec(fields[0])
                if isEdge:
                    if fields[1] == '':
                        errors['emptyNode2Spec'].append(i)
                        continue
                    nodes2 = setFromSpec(fields[1])
                if not isEdge or edgeValues:
                    valTf = fields[-1]
            else:
                if isEdge:
                    if edgeValues:
                        valTf = ''
                        if lfields == normFields - 1:
                            nodes = setFromSpec(fields[0])
                            if fields[1] == '':
                                errors['emptyNode2Spec'].append(i)
                                continue
                            nodes2 = setFromSpec(fields[1])
                        elif lfields == normFields - 2:
                            nodes = {implicit_node}
                            if fields[0] == '':
                                errors['emptyNode2Spec'].append(i)
                                continue
                            nodes2 = setFromSpec(fields[0])
                        else:
                            nodes = {implicit_node}
                            errors['emptyNode2Spec'].append(i)
                            continue
                    else:
                        if lfields == normFields - 1:
                            nodes = {implicit_node}
                            if fields[0] == '':
                                errors['emptyNode2Spec'].append(i)
                                continue
                            nodes2 = setFromSpec(fields[0])
                        else:
                            nodes = {implicit_node}
                            errors['emptyNode2Spec'].append(i)
                            continue
                else:
                    nodes = {implicit_node}
                    if lfields == 1:
                        valTf = fields[0]
                    else:
                        valTf = ''
            implicit_node = max(nodes) + 1
            if not isEdge or edgeValues:
                value = '' if valTf == '' else valueFromTf(valTf)
            if isEdge:
                for n in nodes:
                    for m in nodes2:
                        if not edgeValues:
                            data.setdefault(n, set()).add(m)
                        else:
                            data.setdefault(n, {})[m] = value
            else:
                for n in nodes: data[n] = value
        for kind in errors:
            lnk = len(errors[kind])
            self.tm.error('{} in lines {}\n'.format(kind, ','.join(str(ln) for ln in errors[kind][0:ERROR_CUTOFF])))
            if lnk > ERROR_CUTOFF:
                self.tm.error('\t and {} more cases\n'.format(lnk - ERROR_CUTOFF), tm=False)
        self.data = data
        if not errors:
            if self.fileName == SKELETON[0]:
                monadType = data[0]
                otype = []
                maxMonad = -1
                for n in sorted(data):
                    if data[n] == monadType:
                        maxMonad += 1
                        continue
                    otype.append(data[n])
                otype.append(monadType)
                otype.append(maxMonad)
                self.data = tuple(otype)
            elif self.fileName == SKELETON[1]:
                monadsList = sorted(data)
                maxMonad = min(data.keys()) - 1
                monads = []
                for n in monadsList:
                    monads.append(tuple(sorted(data[n])))
                monads.append(maxMonad)
                self.data = tuple(monads)
        return not errors

    def _compute(self):
        good = True
        for feature in self.dependencies:
            if not feature.load():
                good = False
        if not good: return False

        cmpFormat = 'c {:<20} {{}}\n'.format(self.fileName)
        ctm = Timestamp(level=2)
        def info(msg, tm=True): ctm.info(cmpFormat.format(msg), tm=tm)
        def error(msg, tm=True): ctm.error(cmpFormat.format(msg), tm=tm)
        self.data = self.method(info, error, *[dep.data for dep in self.dependencies])
        return self.data != None

    def _writeTf(self, dirName=None, fileName=None, extension=None, metaOnly=False, nodeRanges=False):
        dirName = dirName or self.dirName
        fileName = fileName or self.fileName
        extension = extension or self.extension
        fpath = '{}/{}{}'.format(dirName, fileName, extension)
        if fpath == self.path:
            if os.path.exists(fpath):
                self.tm.error('Feature file "{}" already exists, feature will not be written\n'.format(fpath))
                return False
        try:
            fh = open(fpath, 'w')
        except:
            self.tm.error('Cannot write to feature file "{}"\n'.format(fpath))
            return False
        fh.write('@{}\n'.format('edge' if self.isEdge else 'node'))
        for meta in sorted(self.metaData):
            fh.write('@{}={}\n'.format(meta, self.metaData[meta]))
        fh.write('@writtenBy=Text-Fabric\n')
        fh.write('@dateWritten={}\n'.format(datetime.utcnow().replace(microsecond=0).isoformat()+'Z'))
        fh.write('\n')
        good = True
        if not metaOnly:
            good = self._writeDataTf(fh, nodeRanges=nodeRanges)
        fh.close()
        return good

    def _writeDataTf(self, fh, nodeRanges=False):
        data = self.data
        edgeValues = self.edgeValues
        if self.isEdge:
            implicitNode = 0
            for n in sorted(data):
                thisData = data[n]
                sets = {}
                if edgeValues:
                    for m in thisData:
                        sets.setdefault(thisData[m], set()).add(m)
                    for (value, mset) in sorted(sets.items()):
                        nodeSpec2 = specFromRanges(rangesFromSet(mset))
                        nodeSpec = '' if n == implicitNode else n
                        implicitNode = n + 1
                        fh.write('{}{}{}\t{}\n'.format(nodeSpec, '\t' if nodeSpec else '', nodeSpec2, tfFromValue(value)))
                else:
                    nodeSpec2 = specFromRanges(rangesFromSet(thisData))
                    nodeSpec = '' if n == implicitNode else n
                    implicitNode = n + 1
                    fh.write('{}{}{}\n'.format(nodeSpec, '\t' if nodeSpec else '', nodeSpec2))
        else:
            sets = {}
            if nodeRanges:
                for n in sorted(data):
                    sets.setdefault(data[n], []).append(n)
                implicitNode = 0
                for (value, nset) in sorted(sets.items(), key=lambda x: (x[1][0], x[1][-1])):
                    if len(nset) == 1 and nset[0] == implicitNode:
                        nodeSpec = ''
                    else:
                        nodeSpec = specFromRanges(rangesFromSet(nset))
                    implicitNode = nset[-1]
                    fh.write('{}{}{}\n'.format(nodeSpec, '\t' if nodeSpec else '', tfFromValue(value)))
            else:
                implicitNode = 0
                for n in sorted(data):
                    nodeSpec = '' if n == implicitNode else n
                    implicitNode = n + 1
                    fh.write('{}{}{}\n'.format(nodeSpec, '\t' if nodeSpec else '', tfFromValue(data[n])))
        return True

    def _readDataBin(self):
        if not os.path.exists(self.binPath):
            self.tm.error('TF reading: feature file "{}" does not exist\n'.format(self.binPath))
            return False
        with gzip.open(self.binPath, "rb") as f: self.data = pickle.load(f)
        return True

    def _writeDataBin(self):
        good = True
        if not os.path.exists(self.binDir):
            try:
                os.makedirs(self.binDir, exist_ok=True)
            except:
                error('Cannot create directory "{}"'.format(self.binDir))
                good = False
        if not good: return False
        try:
            with gzip.open(self.binPath, "wb", compresslevel=GZIP_LEVEL) as f: pickle.dump(self.data, f, protocol=PICKLE_PROTOCOL)
        except:
            error('Cannot write to file "{}"'.format(self.binPath))
            good = False
        return True

    def _getModified(self, bin=False):
        if bin:
            return os.path.getmtime(self.binPath) if os.path.exists(self.binPath) else None
        else:
            if self.method:
                depsInfo = [dep._getModified() for dep in self.dependencies]
                depsModifieds = [d for d in depsInfo if d != None]
                depsModified = None if len(depsModifieds) == 0 else max(depsModifieds)
                if depsModified != None: return depsModified
                elif os.path.exists(self.binPath): return os.path.getmtime(self.binPath)
                else: return None
            else:
                if os.path.exists(self.path): return os.path.getmtime(self.path)
                elif os.path.exists(self.binPath): return os.path.getmtime(self.binPath)
                else: return None
