import pytest
from mlflink import preprocessing as pp
from importlib import resources
import pandas as pd 

# ################################
# RAW 2 CLEAN 
# ################################

# the files we get from resources are "Traversable" so we can concatenante paths like this
# using an / operator and it will do something like `joinpath` in the background
# WORKS FOR ALL OSes
PARQUET_FILE = resources.files("mlflink") / "data" / "test_alerts.parquet"

@pytest.fixture(scope="module")
def alerts_df():
    df = pd.read_parquet(PARQUET_FILE)
    return df

def test_raw2clean(alerts_df):
    clean_df = pp.raw2clean(alerts_df)
    assert not clean_df.empty
    expected_columns = [
        'candid', 'objectId', 'ra', 'dec', 'drb',
        'mjd', 'mag', 'maglim', 'fid', 'isdiffpos',
        'lc_features_g', 'lc_features_r'
    ]
    assert all(col in clean_df.columns for col in expected_columns), "Missing expected columns in cleaned DataFrame"

# ################################
# SHERLOCK
# ################################

# To Mock the Lasair object as we don't want to make an API call everytime
class DummyLasairClient:
    def __init__(self, responses):
        """responses is a list of dicts faking sherlock responses"""
        self._responses = list(responses) # need to make sure it's a list so `pop` works
    def sherlock_position(self, ra, dec, lite=False): 
        # lite is an argument in sherlock API so mock it so we can call the mock with same syntax
        if not self._responses:
            raise RuntimeError("No more dummy responses left")
        return self._responses.pop(0) # returns this first element of the list, then the second etc..
    
@pytest.fixture(scope="module")
def clean_df(alerts_df):
    return pp.raw2clean(alerts_df)

def test_run_sherlock_no_token(clean_df, monkeypatch):
    monkeypatch.delenv('LASAIR_TOKEN', raising=False)
     # make sure the env var is not set
    
    out = pp.run_sherlock(clean_df.copy())
    assert 'sherl_class' in out.columns
    assert 'sep_arcsec' in out.columns
    assert out['sherl_class'].isna().all()
    assert out['sep_arcsec'].isna().all()

def test_run_sherlock_with_mocked_client(monkeypatch, clean_df):
    monkeypatch.setenv('LASAIR_TOKEN', 'fake-token')

    # MOCKED SHERLOCK RESPONSES
    # 1. With a crossmatch and a separation:
    resp_with_cross_match = {
        "classifications": {"transient_00000": ["SN"]},
        "crossmatches": [{"separationArcsec": 1.23}]
    }

    # 2. No crossmatch to hit the IndexError and get a np.nan
    resp_no_match = {
        "classifications": {"transient_00000": ["VS"]},
        "crossmatches": []
    }

    # 3. Cross-match with an AGN
    resp_agn = {
        "classifications": {"transient_00000": ["AGN"]},
        "crossmatches": [{"separationArcsec": 0.45}]
    }

    dummy = DummyLasairClient([
        resp_with_cross_match,
        resp_no_match,
        resp_agn,
    ])

    monkeypatch.setattr(pp, 
                        "lasair", 
                        pp.lasair) # optional, not sure why in here
    
    monkeypatch.setattr(pp.lasair, "lasair_client", 
                        lambda token, 
                        endpoint: dummy # the thing we made above
                        )
    
    # we have 3 mocked responses so we take the first 3 rows of data
    out = pp.run_sherlock(clean_df.iloc[:3].copy()) 

    # pp.run_sherlock filters out AGN and VS — so only SN row should remain
    # Here resp_with_match -> SN (keep), resp_no_match -> VS (removed), resp_other -> AGN (removed)
    assert out.shape[0] == 1
    assert out.iloc[0]['sherl_class'] == "SN"
    assert pytest.approx(out.iloc[0]['sep_arcsec']) == "1.23"