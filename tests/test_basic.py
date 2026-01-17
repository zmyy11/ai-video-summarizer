import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models.transcript import Transcript
from src.models.summary import SummaryResult
from src.utils.chunker import Chunker
from src.core.video import VideoSource

def test_imports():
    print("Imports successful")
    
def test_chunker_init():
    chunker = Chunker()
    print("Chunker initialized")

if __name__ == "__main__":
    test_imports()
    test_chunker_init()
