from pathlib import Path
import tempfile,sys,unittest,os
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc.resource_io import ResourceIO
from wsc.bound_windows_io import BoundWindowsIO,file_api
from wsc.contracts import WSCError


class BoundWindowsIOTests(unittest.TestCase):
    def test_same_bytes_conflicts_and_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'data';raw=b'original\x00\xff'*100
            original=ResourceIO();fast=BoundWindowsIO();original.write_once(path,raw)
            self.assertIs(BoundWindowsIO._fd,ResourceIO._fd)
            self.assertEqual(original.capabilities(),fast.capabilities())
            self.assertEqual(original.digest(path),fast.digest(path));self.assertEqual(original.bytes_read,fast.bytes_read)
            fast.write_once(path,raw)
            with self.assertRaisesRegex(WSCError,'conflict'):fast.write_once(path,b'wrong')
            self.assertEqual(raw,path.read_bytes())
            directory_errors=[]
            for reader in (original,fast):
                with self.assertRaises(FileNotFoundError):reader.digest(root/'missing')
                with self.assertRaises((OSError,WSCError)) as caught:reader.digest(root)
                error=caught.exception;directory_errors.append((type(error),getattr(error,'errno',None),getattr(error,'winerror',None),str(error)))
            self.assertEqual(*directory_errors)
    @unittest.skipUnless(os.name=='nt','Windows sharing invariant')
    def test_read_lease_still_denies_replacement_and_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'data';path.write_bytes(b'old')
            for kind in (ResourceIO,BoundWindowsIO):
                other=root/'replacement';other.write_bytes(b'new')
                with kind().opened(path):
                    with self.assertRaises(OSError):os.replace(other,path)
                    with self.assertRaises(OSError):path.write_bytes(b'new')
                self.assertEqual(b'old',path.read_bytes())
            self.assertIs(file_api(),file_api())


if __name__=='__main__':unittest.main()
