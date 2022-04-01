import fsspec
import numpy as np
import pytest
import xarray as xr

from kerchunk.hdf import SingleHdf5ToZarr
from kerchunk.combine import MultiZarrToZarr, drop


def test_single():
    """Test creating references for a single HDF file"""
    url = 's3://noaa-nwm-retro-v2.0-pds/full_physics/2017/201704010000.CHRTOUT_DOMAIN1.comp'
    so = dict(
        anon=True, default_fill_cache=False, default_cache_type="none"
    )
    with fsspec.open(url, **so) as f:
        h5chunks = SingleHdf5ToZarr(f, url)
        test_dict = h5chunks.translate()

    m = fsspec.get_mapper(
         "reference://",
         fo=test_dict,
         remote_protocol="s3",
         remote_options=so
    )
    ds = xr.open_dataset(m, engine="zarr", backend_kwargs=dict(consolidated=False))

    with fsspec.open(url, **so) as f:
        expected = xr.open_dataset(f, engine="h5netcdf")
    
        xr.testing.assert_equal(ds.drop_vars('crs'), expected.drop_vars('crs'))


urls = ["s3://" + p for p in [
    'noaa-nwm-retro-v2.0-pds/full_physics/2017/201704010000.CHRTOUT_DOMAIN1.comp',
    'noaa-nwm-retro-v2.0-pds/full_physics/2017/201704010100.CHRTOUT_DOMAIN1.comp',
    'noaa-nwm-retro-v2.0-pds/full_physics/2017/201704010200.CHRTOUT_DOMAIN1.comp',
]]
so = dict(
    anon=True, default_fill_cache=False, default_cache_type='first'
)


def test_multizarr(generate_mzz):
    """Test creating a combined reference file with MultiZarrToZarr"""
    mzz = generate_mzz
    test_dict = mzz.translate()

    m = fsspec.get_mapper(
        "reference://",
        fo=test_dict,
        remote_protocol="s3",
        remote_options=so
    )
    ds = xr.open_dataset(m, engine="zarr", backend_kwargs=dict(consolidated=False))

    with fsspec.open_files(urls, **so) as fs:
        expts = [xr.open_dataset(f, engine="h5netcdf") for f in fs]
        expected = xr.concat(expts, dim="time")

        assert set(ds) == set(expected)
        for name in ds:
            exp = {k: (v.tolist() if v.size > 1 else v[0]) if isinstance(v, np.ndarray) else v for k, v in
                   expected[name].attrs.items()}
            assert dict(ds[name].attrs) == dict(exp)
        for coo in ds.coords:
            assert (ds[coo].values == expected[coo].values).all()


@pytest.fixture(scope="module")
def generate_mzz():
    """This function generates a MultiZarrToZarr class for use with the ``example_multizarr*.py`` testss"""

    dict_list = []

    for u in urls:
        with fsspec.open(u, **so) as inf:
            h5chunks = SingleHdf5ToZarr(inf, u, inline_threshold=100)
            dict_list.append(h5chunks.translate())

    mzz = MultiZarrToZarr(
        dict_list,
        remote_protocol="s3",
        remote_options={'anon': True},
        concat_dims=["time"],
        preprocess=drop("reference_time")
    )
    return mzz


def test_times(tmpdir):
    # Test taken from https://github.com/fsspec/kerchunk/issues/115#issue-1091163872
    lat = xr.DataArray(np.linspace(-90, 90, 10), dims=["lat"], name="lat")
    lon = xr.DataArray(np.linspace(-90, 90, 10), dims=["lon"], name="lon")
    time_attrs = {'axis': 'T', 'long_name': 'time', 'standard_name': 'time'}
    time1 = xr.DataArray(
        np.arange(-631108800000000000, -630158390000000000, 86400000000000).view("datetime64[ns]"),
        dims=["time"], name="time", attrs=time_attrs
    )

    x1 = xr.DataArray(
        np.zeros((12, 10, 10)),
        dims=["time", "lat", "lon"],
        coords={"time": time1, "lat": lat, "lon": lon},
        name="prcp",
    )
    url = str(tmpdir.join("x1.nc"))
    x1.to_netcdf(url, engine="h5netcdf")

    with fsspec.open(url) as f:
        h5chunks = SingleHdf5ToZarr(f, url)
        test_dict = h5chunks.translate()

    m = fsspec.get_mapper(
        "reference://",
        fo=test_dict,
    )
    result = xr.open_dataset(m, engine="zarr", backend_kwargs=dict(consolidated=False))
    expected = x1.to_dataset()
    xr.testing.assert_equal(result, expected)
