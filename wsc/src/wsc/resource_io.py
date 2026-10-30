"""Opt-in bounded object I/O and Windows installation-time path leases.

Leases protect named regular files and their directory entries through a host
callback. They do not replace the host's atomic commit/receipt contract.
"""
from contextlib import contextmanager,ExitStack
from hashlib import sha256
from pathlib import Path
import os
import stat
import tempfile
from time import monotonic
from .contracts import WSCError,require


class ResourceIO:
    def __init__(self,*,chunk_bytes=65536,sync_directory=False,max_open_handles=4096):
        require(type(chunk_bytes) is int and chunk_bytes>0,'resource_chunk_budget_invalid')
        require(type(sync_directory) is bool,'resource_sync_policy_invalid')
        self.chunk_bytes=chunk_bytes;self.sync_directory=sync_directory
        require(type(max_open_handles) is int and max_open_handles>0,'resource_handle_budget_invalid')
        self.max_open_handles=max_open_handles
        self.bytes_read=0

    @staticmethod
    def _windows_api():
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        create=kernel.CreateFileW
        create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        create.restype=wintypes.HANDLE
        return kernel,create

    def _fd(self,path,*,directory=False):
        if os.name=='nt':
            import ctypes,msvcrt
            from ctypes import wintypes
            kernel,create=self._windows_api()
            flags=0x00200000|(0x02000000 if directory else 0) # OPEN_REPARSE_POINT, BACKUP_SEMANTICS
            handle=create(str(path),0x80000000,3 if directory else 1,None,3,flags,None)
            if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
            try:return msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
            except BaseException:
                close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close(handle);raise
        return os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))

    @contextmanager
    def opened(self,path,*,directory=False):
        path=Path(path)
        fd=self._fd(path,directory=directory)
        try:
            info=os.fstat(fd)
            require(not getattr(info,'st_file_attributes',0)&0x400,'evidence_path_symlink')
            require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),'evidence_resource_not_regular')
            yield fd
            after=os.fstat(fd);current=os.stat(path,follow_symlinks=False)
            require((info.st_dev,info.st_ino)==(current.st_dev,current.st_ino),'evidence_resource_changed')
            if not directory:
                require((info.st_size,info.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'evidence_resource_changed')
        finally:os.close(fd)

    def equal(self,path,payload):
        with self.opened(path) as fd:
            if os.fstat(fd).st_size!=len(payload):return False
            offset=0
            while True:
                value=os.read(fd,self.chunk_bytes);self.bytes_read+=len(value)
                if not value:return offset==len(payload)
                if value!=payload[offset:offset+len(value)]:return False
                offset+=len(value)

    def digest(self,path,*,max_bytes=None,deadline=None):
        require(max_bytes is None or type(max_bytes) is int and max_bytes>=0,'resource_read_budget_invalid')
        require(deadline is None or type(deadline) in (int,float),'resource_read_deadline_invalid')
        hasher=sha256();total=0
        with self.opened(path) as fd:
            while True:
                require(deadline is None or monotonic()<=deadline,'resource_read_deadline_exceeded')
                value=os.read(fd,self.chunk_bytes if max_bytes is None else min(self.chunk_bytes,max_bytes-total+1))
                self.bytes_read+=len(value);total+=len(value)
                if not value:break
                require(max_bytes is None or total<=max_bytes,'reference_resource_changed')
                hasher.update(value)
        return hasher.hexdigest()

    def read_bounded(self,path,max_bytes,*,deadline=None):
        require(type(max_bytes) is int and max_bytes>=0,'resource_read_budget_invalid')
        require(deadline is None or type(deadline) in (int,float),'resource_read_deadline_invalid')
        values=[];remaining=max_bytes
        with self.opened(path) as fd:
            while remaining:
                require(deadline is None or monotonic()<=deadline,'resource_read_deadline_exceeded')
                value=os.read(fd,min(self.chunk_bytes,remaining));self.bytes_read+=len(value)
                if not value:break
                values.append(value);remaining-=len(value)
        return b''.join(values)

    def capabilities(self):
        return dict(atomic_no_replace_publication=True,file_fsync=True,
            directory_fsync_requested=self.sync_directory,
            directory_fsync_platform_path=os.name!='nt',directory_fsync_verified=False,
            windows_directory_durability_verified=False,
            installation_path_leases=os.name=='nt',
            power_loss_recovery_proven=False,max_lease_handles=self.max_open_handles)

    def _sync(self,directory):
        if not self.sync_directory:return
        require(os.name!='nt','directory_sync_unavailable')
        fd=os.open(directory,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(fd)
        finally:os.close(fd)

    def write_once(self,path,payload):
        path=Path(path)
        require(not (self.sync_directory and os.name=='nt'),'directory_sync_unavailable')
        try:
            try:
                require(self.equal(path,payload),'evidence_object_conflict');return
            except FileNotFoundError:pass
            fd,temp=tempfile.mkstemp(prefix='.pending-',dir=path.parent);temp=Path(temp)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(payload);stream.flush();os.fsync(stream.fileno())
                try:os.link(temp,path)
                except FileExistsError:require(self.equal(path,payload),'evidence_object_conflict')
                self._sync(path.parent)
            finally:
                temp.unlink(missing_ok=True);self._sync(path.parent)
        except OSError:
            raise WSCError('evidence_object_unavailable') from None

    @contextmanager
    def publication_writer(self):
        """Memoize only while Windows sharing rules pin the actual object."""
        cache={}
        with ExitStack() as stack:
            def write(path,payload):
                path=Path(path);signature=(len(payload),sha256(payload).digest())
                if path in cache:
                    require(cache[path]==signature,'evidence_object_conflict');return
                self.write_once(path,payload)
                if os.name!='nt' or len(cache)>=min(128,self.max_open_handles):return
                fd=stack.enter_context(self.opened(path))
                hasher=sha256();length=0
                while True:
                    value=os.read(fd,self.chunk_bytes);self.bytes_read+=len(value)
                    if not value:break
                    length+=len(value);hasher.update(value)
                require((length,hasher.digest())==signature,'evidence_object_conflict')
                cache[path]=signature
            yield write

    @contextmanager
    def lease(self,package):
        require(os.name=='nt','installation_resource_lease_unavailable')
        paths=set()
        def collect(value):
            if isinstance(value,dict):
                for key in ('file_path','readable_path'):
                    if key in value:paths.add(Path(value[key]))
                for nested in value.values():collect(nested)
            elif isinstance(value,list):
                for nested in value:collect(nested)
        collect(package.get('evidence',{}));collect(package.get('excerpt_evidence',{}));collect(package.get('adapter',{}).get('projection_evidence',{}))
        paths.update(Path(package[k]) for k in ('source_index','understanding_index'))
        paths.update(Path(b['resource']) for b in package.get('current_reference_bindings',[]) if b.get('status')=='unique_content_match')
        directories={p for path in paths for p in path.parents}
        require(len(paths)+len(directories)<=self.max_open_handles,'installation_resource_budget_exhausted')
        stack=ExitStack()
        try:
            for path in sorted(directories,key=lambda p:(len(p.parts),str(p))):stack.enter_context(self.opened(path,directory=True))
            for path in sorted(paths,key=str):stack.enter_context(self.opened(path))
        except OSError:
            stack.close();raise WSCError('installation_resource_unavailable') from None
        except BaseException:
            stack.close();raise
        with stack:yield
