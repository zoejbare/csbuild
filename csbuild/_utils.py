# Copyright (C) 2013 Jaedyn K. Draper
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import log
import _shared_globals
import fnmatch
import os
import re
import shlex
import hashlib
import subprocess
import threading
import time
import sys
import math
import datetime
import projectSettings as currentProject


def get_files(project, sources=None, headers=None):
    """
    Steps through the current directory tree and finds all of the source and header files, and returns them as a list.
    Accepts two lists as arguments, which it populates. If sources or headers are excluded from the parameters, it will
    ignore files of the relevant types.
    """
    for root, dirnames, filenames in os.walk('.'):
        absroot = os.path.abspath(root)
        if absroot in project.globalDict.exclude_dirs:
            if absroot != project.globalDict.csbuild_dir:
                log.LOG_INFO("Skipping dir {0}".format(root))
            continue
        if absroot == project.globalDict.csbuild_dir or absroot.startswith(project.globalDict.csbuild_dir):
            continue
        bFound = False
        for testDir in project.globalDict.exclude_dirs:
            if absroot.startswith(testDir):
                bFound = True
                break
        if bFound:
            if not absroot.startswith(project.globalDict.csbuild_dir):
                log.LOG_INFO("Skipping dir {0}".format(root))
            continue
        log.LOG_INFO("Looking in directory {0}".format(root))
        if sources is not None:
            for filename in fnmatch.filter(filenames, '*.cpp'):
                path = os.path.join(root, filename)
                if path not in project.globalDict.exclude_files:
                    sources.append(os.path.abspath(path))
            for filename in fnmatch.filter(filenames, '*.c'):
                path = os.path.join(root, filename)
                if path not in project.globalDict.exclude_files:
                    sources.append(os.path.abspath(path))

            sources.sort(key=str.lower)

        if headers is not None:
            for filename in fnmatch.filter(filenames, '*.hpp'):
                path = os.path.join(root, filename)
                if path not in project.globalDict.exclude_files:
                    headers.append(os.path.abspath(path))
            for filename in fnmatch.filter(filenames, '*.h'):
                path = os.path.join(root, filename)
                if path not in project.globalDict.exclude_files:
                    headers.append(os.path.abspath(path))
            for filename in fnmatch.filter(filenames, '*.inl'):
                path = os.path.join(root, filename)
                if path not in project.globalDict.exclude_files:
                    headers.append(os.path.abspath(path))

            headers.sort(key=str.lower)


def follow_headers(headerFile, allheaders):
    """Follow the headers in a file.
    First, this will check to see if the given header has been followed already.
    If it has, it pulls the list from the allheaders global dictionary and returns it.
    If not, it populates a new allheaders list with follow_headers2, and then adds
    that to the allheaders dictionary
    """
    headers = []
    if not headerFile:
        return

    if headerFile in _shared_globals.allheaders:
        return

    with open(headerFile) as f:
        for line in f:
            if line[0] != '#':
                continue

            RMatch = re.search("#include\s*[<\"](.*?)[\">]", line)
            if RMatch is None:
                continue

            if "." not in RMatch.group(1):
                continue

            headers.append(RMatch.group(1))

    for header in headers:
        #If we've already looked at this header (i.e., it was included twice) just ignore it
        if header in allheaders:
            continue

        if header in _shared_globals.allheaders:
            continue

        #Find the header in the listed includes.
        path = "{0}/{1}".format(os.path.dirname(headerFile), header)
        if not os.path.exists(path):
            for incDir in currentProject.include_dirs:
                path = "{0}/{1}".format(incDir, header)
                if os.path.exists(path):
                    break
                    #A lot of standard C and C++ headers will be in a compiler-specific directory that we won't check.
                    #Just ignore them to speed things up.
        if not os.path.exists(path):
            continue

        if currentProject.ignore_external_headers and not path.startswith("./"):
            continue

        allheaders.append(header)

        theseheaders = set()

        if currentProject.header_recursion != 1:
            #Check to see if we've already followed this header.
            #If we have, the list we created from it is already stored in _allheaders under this header's key.
            try:
                allheaders += _shared_globals.allheaders[header]
            except KeyError:
                pass
            else:
                continue

            follow_headers2(path, theseheaders, 1)

        _shared_globals.allheaders.update({header: theseheaders})
        allheaders += theseheaders


def follow_headers2(headerFile, allheaders, n):
    """More intensive, recursive, and cpu-hogging function to follow a header.
    Only executed the first time we see a given header; after that the information is cached."""
    headers = []
    if not headerFile:
        return
    with open(headerFile) as f:
        for line in f:
            if line[0] != '#':
                continue

            RMatch = re.search("#include\s*[<\"](.*?)[\">]", line)
            if RMatch is None:
                continue

            if "." not in RMatch.group(1):
                continue

            headers.append(RMatch.group(1))

    for header in headers:
        #Check to see if we've already followed this header.
        #If we have, the list we created from it is already stored in _allheaders under this header's key.
        if header in allheaders:
            continue

        if header in _shared_globals.allheaders:
            continue

        path = "{0}/{1}".format(os.path.dirname(headerFile), header)
        if not os.path.exists(path):
            for incDir in currentProject.include_dirs:
                path = "{0}/{1}".format(incDir, header)
                if os.path.exists(path):
                    break
                    #A lot of standard C and C++ headers will be in a compiler-specific directory that we won't check.
                    #Just ignore them to speed things up.
        if not os.path.exists(path):
            continue

        if currentProject.ignore_external_headers and not path.startswith("./"):
            continue

        allheaders.add(header)

        theseheaders = set(allheaders)

        if currentProject.header_recursion == 0 or n < currentProject.header_recursion:
            #Check to see if we've already followed this header.
            #If we have, the list we created from it is already stored in _allheaders under this header's key.
            try:
                allheaders += _shared_globals.allheaders[header]
            except KeyError:
                pass
            else:
                continue

            follow_headers2(path, theseheaders, n + 1)

        _shared_globals.allheaders.update({header: theseheaders})
        allheaders |= theseheaders


def remove_comments(text):
    def replacer(match):
        s = match.group(0)
        if s.startswith('/'):
            return ""
        else:
            return s

    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE
    )
    return re.sub(pattern, replacer, text)


def remove_whitespace(text):
    #This isn't working correctly, turning it off.
    return text
    #shlexer = shlex.shlex(text)
    #out = []
    #token = ""
    #while True:
    #    token = shlexer.get_token()
    #    if token == "":
    #        break
    #    out.append(token)
    #return "".join(out)


def get_md5(inFile):
    return hashlib.md5(remove_whitespace(remove_comments(inFile.read()))).digest()


def should_recompile(srcFile, ofile=None, for_precompiled_header=False):
    """Checks various properties of a file to determine whether or not it needs to be recompiled."""

    log.LOG_INFO("Checking whether to recompile {0}...".format(srcFile))

    if currentProject.recompile_all:
        log.LOG_INFO(
            "Going to recompile {0} because settings have changed in the makefile that will impact output.".format(
                srcFile))
        return True

    basename = os.path.basename(srcFile).split('.')[0]
    if not ofile:
        ofile = "{0}/{1}_{2}.o".format(currentProject.obj_dir, basename, currentProject.targetName)

    if currentProject.use_chunks:
        chunk = get_chunk(srcFile)
        chunkfile = "{0}/{1}_{2}.o".format(currentProject.obj_dir, chunk, currentProject.targetName)

        #First check: If the object file doesn't exist, we obviously have to create it.
        if not os.path.exists(ofile):
            ofile = chunkfile

    if not os.path.exists(ofile):
        log.LOG_INFO("Going to recompile {0} because the associated object file does not exist.".format(srcFile))
        return True

    #Third check: modified time.
    #If the source file is newer than the object file, we assume it's been changed and needs to recompile.
    mtime = os.path.getmtime(srcFile)
    omtime = os.path.getmtime(ofile)

    if mtime > omtime:
        oldmd5 = 1
        newmd5 = 9

        try:
            newmd5 = _shared_globals.newmd5s[srcFile]
        except KeyError:
            with open(srcFile, "r") as f:
                newmd5 = get_md5(f)
            _shared_globals.newmd5s.update({srcFile: newmd5})

        md5file = "{0}/md5s/{1}.md5".format(currentProject.csbuild_dir, os.path.abspath(srcFile))

        if os.path.exists(md5file):
            try:
                oldmd5 = _shared_globals.oldmd5s[md5file]
            except KeyError:
                with open(md5file, "r") as f:
                    oldmd5 = f.read()
                _shared_globals.oldmd5s.update({md5file: oldmd5})

        if oldmd5 != newmd5:
            log.LOG_INFO(
                "Going to recompile {0} because it has been modified since the last successful build.".format(srcFile))
            return True

    #Fourth check: Header files
    #If any included header file (recursive, to include headers included by headers) has been changed,
    #then we need to recompile every source that includes that header.
    #Follow the headers for this source file and find out if any have been changed o necessitate a recompile.
    headers = []
    follow_headers(srcFile, headers)

    updatedheaders = []

    for header in headers:
        path = "{0}/{1}".format(os.path.dirname(srcFile), header)
        if not os.path.exists(path):
            for incDir in currentProject.include_dirs:
                path = "{0}/{1}".format(incDir, header)
                if os.path.exists(path):
                    break
                    #A lot of standard C and C++ headers will be in a compiler-specific directory that we won't check.
                    #Just ignore them to speed things up.
        if not os.path.exists(path):
            continue

        header_mtime = os.path.getmtime(path)

        if header_mtime > omtime:
            #newmd5 is 0, oldmd5 is 1, so that they won't report equal if we ignore them.
            newmd5 = 0
            oldmd5 = 1

            md5file = "{0}/md5s/{1}.md5".format(currentProject.csbuild_dir, os.path.abspath(path))

            if os.path.exists(md5file):
                try:
                    newmd5 = _shared_globals.newmd5s[path]
                except KeyError:
                    with open(path, "r") as f:
                        newmd5 = get_md5(f)
                    _shared_globals.newmd5s.update({path: newmd5})
                if os.path.exists(md5file):
                    try:
                        oldmd5 = _shared_globals.oldmd5s[md5file]
                    except KeyError:
                        with open(md5file, "r") as f:
                            oldmd5 = f.read()
                        _shared_globals.oldmd5s.update({md5file: oldmd5})

            if oldmd5 != newmd5:
                updatedheaders.append([header, path])

    if updatedheaders:
        files = []
        for pair in updatedheaders:
            files.append(pair[0])
            path = pair[1]
            if path not in currentProject.allpaths:
                currentProject.allpaths.append(path)
        log.LOG_INFO(
            "Going to recompile {0} because included headers {1} have been modified since the last successful build."
            .format(
                srcFile, files))
        return True

    #Handle condition where precompiled headers will fail when modified time on a header has changed,
    #but the header itself has not. Just update the timestamp on the object file.
    if for_precompiled_header:
        os.utime(ofile, None)

    #If we got here, we assume the object file's already up to date.
    log.LOG_INFO("Skipping {0}: Already up to date".format(srcFile))
    return False


def check_libraries():
    """Checks the libraries designated by the make script.
    Invokes ld to determine whether or not the library exists.1
    Uses the -t flag to get its location.
    And then stores the library's last modified time to a global list to be used by the linker later, to determine
    whether or not a project with up-to-date objects still needs to link against new libraries.
    """
    libraries_ok = True
    log.LOG_INFO("Checking required libraries...")
    for library in (currentProject.libraries + currentProject.static_libraries):
        log.LOG_INFO("Looking for lib{0}...".format(library))
        success = True
        out = ""
        if os.name == "posix":
            try:
                if _shared_globals.show_commands:
                    print "ld -o /dev/null --verbose {0} -l{1}".format(
                        currentProject.compiler_model.get_library_dirs(currentProject.library_dirs, False),
                        library)
                cmd = ["ld", "-o", "/dev/null", "--verbose", "-l{0}".format(library)]
                cmd += shlex.split(currentProject.compiler_model.get_library_dirs(currentProject.library_dirs, False))
                out = subprocess.check_output(cmd, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                out = e.output
                success = False
            finally:
                mtime = 0
                RMatch = re.search("attempt to open (.*) succeeded".format(re.escape(library)), out)
                #Some libraries (such as -liberty) will return successful but don't have a file (internal to ld maybe?)
                #In those cases we can probably assume they haven't been modified.
                #Set the mtime to 0 and return success as long as ld didn't return an error code.
                if RMatch is not None:
                    lib = RMatch.group(1)
                    mtime = os.path.getmtime(lib)
                    log.LOG_INFO("Found library lib{0} at {1}".format(library, lib))
                elif not success:
                    log.LOG_ERROR("Could not locate library: {0}".format(library))
                    libraries_ok = False
                _shared_globals.library_mtimes.append(mtime)
        else:
            log.LOG_WARN("Library checking not yet implemented in non-posix systems")
    if not libraries_ok:
        log.LOG_ERROR("Some dependencies are not met on your system.")
        log.LOG_ERROR("Check that all required libraries are installed.")
        log.LOG_ERROR(
            "If they are installed, ensure that the path is included in the makefile (use csbuild.LibDirs() to set "
            "them)")
        return False
    log.LOG_INFO("Libraries OK!")
    return True


class threaded_build(threading.Thread):
    """Multithreaded build system, launches a new thread to run the compiler in.
    Uses a threading.BoundedSemaphore object to keep the number of threads equal to the number of processors on the
    machine.
    """

    def __init__(self, infile, inobj, proj):
        """Initialize the object. Also handles above-mentioned bug with dummy threads."""
        threading.Thread.__init__(self)
        self.file = infile
        self.obj = os.path.abspath(inobj)
        self.project = proj
        #Prevent certain versions of python from choking on dummy threads.
        if not hasattr(threading.Thread, "_Thread__block"):
            threading.Thread._Thread__block = _shared_globals.dummy_block()

    def run(self):
        """Actually run the build process."""
        starttime = time.time()
        try:
            inc = ""
            if (
                self.project.globalDict.precompile or self.project.globalDict.chunk_precompile) and self.project.globalDict.headerfile and self.file != self\
                .project.globalDict.headerfile:
                inc += "-include {0}".format(self.project.globalDict.headerfile.rsplit(".", 1)[0])
            cmd = "{0} {1}{2}{3} -o\"{4}\" \"{5}\"".format(self.project.globalDict.cmd,
                self.project.globalDict.compiler_model.get_warnings(self.project.globalDict.warn_flags, self.project.globalDict.no_warnings),
                self.project.globalDict.compiler_model.get_include_dirs(self.project.globalDict.include_dirs), inc, self.obj,
                os.path.abspath(self.file))
            if _shared_globals.show_commands:
                print(cmd)
            if os.path.exists(self.obj):
                os.remove(self.obj)
                #We have to use os.popen here, not subprocess.call. For some reason, subprocess.call likes to freeze
                # here, but os.popen works fine.
            fd = os.popen(cmd)
            output = fd.read()
            ret = fd.close()
            sys.stdout.flush()
            sys.stdout.write(output)
            if ret:
                if str(ret) == "2":
                    _shared_globals.lock.acquire()
                    if not _shared_globals.interrupted:
                        log.LOG_ERROR("Keyboard interrupt received. Aborting build.")
                    _shared_globals.interrupted = True
                    log.LOG_BUILD("Releasing lock...")
                    _shared_globals.lock.release()
                    log.LOG_BUILD("Releasing semaphore...")
                    _shared_globals.semaphore.release()
                    log.LOG_BUILD("Closing thread...")
                if not _shared_globals.interrupted:
                    log.LOG_ERROR("Compile of {0} failed!".format(self.file, ret))
                _shared_globals.build_success = False
                self.project.globalDict.compile_failed = True
                self.project.globalDict.compiles_completed += 1
        except Exception as e:
            #If we don't do this with ALL exceptions, any unhandled exception here will cause the semaphore to never
            # release...
            #Meaning the build will hang. And for whatever reason ctrl+c won't fix it.
            #ABSOLUTELY HAVE TO release the semaphore on ANY exception.
            #if os.path.dirname(self.file) == _csbuild_dir:
            #   os.remove(self.file)
            _shared_globals.semaphore.release()
            self.project.globalDict.compile_failed = True
            self.project.globalDict.compiles_completed += 1
            raise e
        else:
            #if os.path.dirname(self.file) == _csbuild_dir:
            #   os.remove(self.file)
            #if inc or (not self.project.globalDict.precompile and not self.project.globalDict.chunk_precompile):
            endtime = time.time()
            _shared_globals.times.append(endtime - starttime)
            _shared_globals.semaphore.release()
            self.project.globalDict.compiles_completed += 1


def make_chunks(l):
    """ Converts the list into a list of lists - i.e., "chunks"
    Each chunk represents one compilation unit in the chunked build system.
    """
    sorted_list = sorted(l, key=os.path.getsize, reverse=True)
    if currentProject.unity or not currentProject.use_chunks:
        return [l]
    chunks = []
    if currentProject.chunk_filesize > 0:
        chunksize = 0
        chunk = []
        while sorted_list:
            chunksize = 0
            chunk = [sorted_list[0]]
            chunksize += os.path.getsize(sorted_list[0])
            sorted_list.pop(0)
            for srcFile in reversed(sorted_list):
                filesize = os.path.getsize(srcFile)
                if chunksize + filesize > currentProject.chunk_filesize:
                    chunks.append(chunk)
                    log.LOG_INFO("Made chunk: {0}".format(chunk))
                    log.LOG_INFO("Chunk size: {0}".format(chunksize))
                    break
                else:
                    chunk.append(srcFile)
                    chunksize += filesize
                    sorted_list.pop()
        chunks.append(chunk)
        log.LOG_INFO("Made chunk: {0}".format(chunk))
        log.LOG_INFO("Chunk size: {0}".format(chunksize))
    elif currentProject.chunk_size > 0:
        for i in xrange(0, len(l), currentProject.chunk_size):
            chunks.append(l[i:i + currentProject.chunk_size])
    else:
        return [l]
    return chunks


def base_names(l):
    ret = []
    for srcFile in l:
        ret.append(os.path.basename(srcFile).split(".")[0])
    return ret


def get_chunk(srcFile):
    """Retrieves the chunk that a given file belongs to."""
    for chunk in currentProject.chunks:
        if srcFile in chunk:
            return "{0}_chunk_{1}".format(currentProject.output_name.split('.')[0], "__".join(base_names(chunk)))


def get_size(chunk):
    size = 0
    if type(chunk) == list:
        for source in chunk:
            size += os.path.getsize(source)
        return size
    else:
        return os.path.getsize(chunk)


def chunked_build():
    """Prepares the files for a chunked build.
    This function steps through all of the sources that are on the slate for compilation and determines whether each
    needs to be compiled individually or as a chunk. If it is to be compiled as a chunk, this function also creates
    the chunk file to be compiled. It then returns an updated list of files - individual files, chunk files, or both -
    that are to be compiled.
    """

    chunks_to_build = []
    totalChunks = 0
    owningProject = None

    for project in _shared_globals.projects.values():
        for source in project.globalDict.sources:
            chunk = get_chunk(source)
            if currentProject.unity:
                outFile = "{0}/{1}_unity.cpp".format(project.globalDict.csbuild_dir, project.globalDict.output_name)
            else:
                outFile = "{0}/{1}.cpp".format(project.globalDict.csbuild_dir, chunk)
            if chunk not in chunks_to_build and os.path.exists(outFile):
                chunks_to_build.append(chunk)

        totalChunks += len(project.globalDict.chunks)

        #if we never get a second chunk, we'll want to know about the project that made the first one
        if totalChunks == 1:
            owningProject = project

    #Not enough chunks being built, build as plain files.
    if totalChunks == 0:
        return

    if totalChunks == 1 and not owningProject.globalDict.unity:
        chunkname = "{0}_chunk_{1}".format(owningProject.globalDict.output_name.split('.')[0], "__".join(base_names(owningProject.chunks[0])))
        obj = "{0}/{1}_{2}.o".format(owningProject.globalDict.obj_dir, chunkname, owningProject.globalDict.targetName)
        if os.path.exists(obj):
            log.LOG_WARN_NOPUSH(
                "Breaking chunk ({0}) into individual files to improve future iteration turnaround.".format(owningProject.chunks[0]))
        owningProject.globalDict.final_chunk_set = owningProject.globalDict.sources
        return

    dont_split_any = False
    #If we have to build more than four chunks, or more than a quarter of the total number if that's less than four,
    #then we're not dealing with a "small build" that we can piggyback on to split the chunks back up.
    #Just build them as chunks for now; we'll split them up in another, smaller build.
    if len(chunks_to_build) > min(totalChunks / 4, 4):
        log.LOG_INFO("Not splitting any existing chunks because we would have to build too many.")
        dont_split_any = True

    for project in _shared_globals.projects.values():
        dont_split = dont_split_any
        if project.globalDict.unity:
            dont_split = True

        for chunk in project.globalDict.chunks:
            sources_in_this_chunk = []
            for source in project.globalDict.sources:
                if source in chunk:
                    sources_in_this_chunk.append(source)

            chunksize = get_size(sources_in_this_chunk)

            if project.globalDict.unity:
                outFile = "{0}/{1}_unity.cpp".format(project.globalDict.csbuild_dir, project.globalDict.output_name)
            else:
                outFile = "{0}/{1}_chunk_{2}.cpp".format(project.globalDict.csbuild_dir, project.globalDict.output_name.split('.')[0],
                    "__".join(base_names(chunk)))

            #If only one or two sources in this chunk need to be built, we get no benefit from building it as a unit.
            # Split unless we're told not to.
            if project.globalDict.use_chunks and len(chunk) > 1 and (
                    (project.globalDict.chunk_size > 0 and len(sources_in_this_chunk) > project.globalDict.chunk_tolerance) or (
                                project.globalDict.chunk_filesize > 0 and chunksize > project.globalDict.chunk_size_tolerance) or (
                        dont_split and (project.globalDict.unity or os.path.exists(outFile)) and len(
                        sources_in_this_chunk) > 0)):
                log.LOG_INFO("Going to build chunk {0} as {1}".format(chunk, outFile))
                with open(outFile, "w") as f:
                    f.write("//Automatically generated file, do not edit.\n")
                    for source in chunk:
                        f.write('#include "{0}" // {1} bytes\n'.format(os.path.abspath(source), os.path.getsize(source)))
                        obj = "{0}/{1}_{2}.o".format(project.globalDict.obj_dir, os.path.basename(source).split('.')[0],
                            project.globalDict.targetName)
                        if os.path.exists(obj):
                            os.remove(obj)
                    f.write("//Total size: {0} bytes".format(chunksize))

                project.globalDict.final_chunk_set.append(outFile)
            elif len(sources_in_this_chunk) > 0:
                chunkname = "{0}_chunk_{1}".format(project.globalDict.output_name.split('.')[0], "__".join(base_names(chunk)))
                obj = "{0}/{1}_{2}.o".format(project.globalDict.obj_dir, chunkname, project.globalDict.targetName)
                if os.path.exists(obj):
                    #If the chunk object exists, the last build of these files was the full chunk.
                    #We're now splitting the chunk to speed things up for future incremental builds, which means the chunk
                    #is getting deleted and *every* file in it needs to be recompiled this time only.
                    #The next time any of these files changes, only that section of the chunk will get built.
                    #This keeps large builds fast through the chunked build, without sacrificing the speed of smaller
                    #incremental builds (except on the first build after the chunk)
                    os.remove(obj)
                    add_chunk = chunk
                    if project.globalDict.use_chunks:
                        log.LOG_INFO(
                            "Keeping chunk ({0}) broken up because chunking has been disabled for this project".format(chunk))
                    else:
                        log.LOG_WARN_NOPUSH(
                            "Breaking chunk ({0}) into individual files to improve future iteration turnaround.".format(chunk))
                else:
                    add_chunk = sources_in_this_chunk
                if len(add_chunk) == 1:
                    if len(chunk) == 1:
                        log.LOG_INFO("Going to build {0} as an individual file because it's the only file in its chunk.".format(chunk[0]))
                    else:
                        log.LOG_INFO("Going to build {0} as an individual file.".format(add_chunk))
                else:
                    log.LOG_INFO("Going to build chunk {0} as individual files.".format(add_chunk))
                project.globalDict.final_chunk_set += add_chunk


def save_md5(inFile):
    md5file = "{0}/md5s/{1}.md5".format(currentProject.csbuild_dir, os.path.abspath(inFile))
    md5dir = os.path.dirname(md5file)
    if not os.path.exists(md5dir):
        os.makedirs(md5dir)
    try:
        newmd5 = _shared_globals.newmd5s[inFile]
    except KeyError:
        with open(inFile, "r") as f:
            newmd5 = get_md5(f)
    finally:
        with open(md5file, "w") as f:
            f.write(newmd5)


def save_md5s(sources, headers):
    for source in sources:
        save_md5(source)

    for header in headers:
        save_md5(header)

    for path in currentProject.allpaths:
        save_md5(os.path.abspath(path))


def prepare_precompiles():
    wd = os.getcwd()
    for project in _shared_globals.projects.values():
        os.chdir(project.workingDirectory)
        allheaders = []

        if project.globalDict.chunk_precompile:
            get_files(project, headers=allheaders)
        else:
            allheaders = project.globalDict.precompile

        if not allheaders:
            project.globalDict.needs_precompile = False
            continue

        project.globalDict.headers = allheaders

        if not project.globalDict.precompile and not project.globalDict.chunk_precompile:
            project.globalDict.needs_precompile = False
            continue

        project.globalDict.headerfile = "{0}/{1}_precompiled_headers.hpp".format(project.globalDict.csbuild_dir,
            project.globalDict.output_name.split('.')[0])

        obj = "{0}/{1}_{2}.hpp.gch".format(os.path.dirname(project.globalDict.headerfile),
            os.path.basename(project.globalDict.headerfile).split('.')[0],
            project.globalDict.targetName)

        precompile = False
        if not os.path.exists(project.globalDict.headerfile) or should_recompile(project.globalDict.headerfile, obj, True):
            precompile = True
        else:
            for header in allheaders:
                if should_recompile(header, obj, True):
                    precompile = True
                    break

        if not precompile:
            project.globalDict.headerfile = obj
            project.globalDict.needs_precompile = False
            continue

        with open(project.globalDict.headerfile, "w") as f:
            for header in allheaders:
                if header in project.globalDict.precompile_exclude:
                    continue
                f.write('#include "{0}"\n'.format(os.path.abspath(header)))

        _shared_globals.total_precompiles += 1
    os.chdir(wd)


#TODO: Parallelize
def precompile_headers(proj):
    if not proj.globalDict.needs_precompile:
        return True

    starttime = time.time()
    log.LOG_BUILD("Precompiling headers...")

    _shared_globals.built_something = True

    if not os.path.exists(proj.globalDict.obj_dir):
        os.makedirs(proj.globalDict.obj_dir)

    if not _shared_globals.semaphore.acquire(False):
        if _shared_globals.max_threads != 1:
            log.LOG_THREAD("Waiting for a build thread to become available...")
            _shared_globals.semaphore.acquire(True)
    if _shared_globals.interrupted:
        sys.exit(2)

    log.LOG_BUILD(
        "Precompiling {0} ({1}/{2})...".format(
            proj.globalDict.headerfile,
            _shared_globals.current_compile,
            _shared_globals.total_compiles))

    obj = "{0}/{1}_{2}.hpp.gch".format(os.path.dirname(proj.globalDict.headerfile),
        os.path.basename(proj.globalDict.headerfile).split('.')[0],
        proj.globalDict.targetName)

    #precompiled headers block on current thread - run runs on current thread rather than starting a new one
    threaded_build(proj.globalDict.headerfile, obj, proj).run()

    proj.globalDict.headerfile = obj

    totaltime = time.time() - starttime
    totalmin = math.floor(totaltime / 60)
    totalsec = round(totaltime % 60)
    log.LOG_BUILD("Precompile took {0}:{1:02}".format(int(totalmin), int(totalsec)))

    _shared_globals.precompiles_done += 1
    _shared_globals.current_compile += 1
    proj.globalDict.precompile_done = True

    return _shared_globals.build_success


def get_base_name(name):
    """This converts an output name into a directory name. It removes extensions, and also removes the prefix 'lib'"""
    ret = name.split(".")[0]
    if ret.startswith("lib"):
        ret = ret[3:]
    return ret


def check_version():
    """Checks the currently installed version against the latest version, and logs a warning if the current version
    is out of date."""
    with open(os.path.dirname(__file__) + "/version", "r") as f:
        csbuild_version = f.read()
    if not os.path.exists(os.path.expanduser("~/.csbuild/check")):
        csbuild_date = ""
    else:
        with open(os.path.expanduser("~/.csbuild/check"), "r") as f:
            csbuild_date = f.read()

    date = datetime.date.today().isoformat()

    if date == csbuild_date:
        return

    if not os.path.exists(os.path.expanduser("~/.csbuild")):
        os.makedirs(os.path.expanduser("~/.csbuild"))

    with open(os.path.expanduser("~/.csbuild/check"), "w") as f:
        f.write(date)

    try:
        out = subprocess.check_output(["pip", "search", "csbuild"])
    except:
        return
    else:
        RMatch = re.search("LATEST:\s*(\S*)$", out)
        if not RMatch:
            return
        latest_version = RMatch.group(1)
        if latest_version != csbuild_version:
            log.LOG_WARN(
                "A new version of csbuild is available. Current version: {0}, latest: {1}".format(csbuild_version,
                    latest_version))
            log.LOG_WARN("Use 'sudo pip install csbuild --upgrade' to get the latest version.")


def sortProjects():
    ret = []

    def insert_depends(project, already_inserted=set()):
        already_inserted.add(project.name)
        for depend in project.linkDepends:
            if depend in already_inserted:
                log.LOG_ERROR("Circular dependencies detected: {0} and {1} in linkDepends".format(depend, project.name))
                sys.exit(1)
            insert_depends(_shared_globals.projects[depend], already_inserted)
        for depend in project.srcDepends:
            if depend in already_inserted:
                log.LOG_ERROR("Circular dependencies detected: {0} and {1} in srcDepends".format(depend, project.name))
                sys.exit(1)
            insert_depends(_shared_globals.projects[depend], already_inserted)
        if project not in ret:
            ret.append(project)
        already_inserted.remove(project.name)

    for project in _shared_globals.projects.values():
        insert_depends(project)

    return ret