import sys, traceback
sys.path.insert(0, r'c:/Users/DELL/Downloads/mednova_os_web 6/mednova_os_web 6')
from backend.sync.sync_engine import SyncEngine

engine = SyncEngine()
try:
    result = engine.run()
    print(result)
except Exception:
    traceback.print_exc()
