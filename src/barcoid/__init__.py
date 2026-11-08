"""
BarcoID: Multi-Source DNA Barcode Taxonomic Identifier, Cross-Referencer & QC Auditor.
"""

__version__ = "0.1.0"
__author__ = "Jakub Šidlík"

from barcoid.config import BarcoIDConfig
from barcoid.cache import CacheManager
from barcoid.pipeline import BarcoIDPipeline

__all__ = ["__version__", "BarcoIDConfig", "CacheManager", "BarcoIDPipeline"]
