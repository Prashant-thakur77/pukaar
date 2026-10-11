"""Sentinel-2 crops for the pitch video (video/pitch-media.mjs runs `get`). List Sentinel-2 L2A candidates over a bbox and rank by crop cloud (SCL).
usage: s2.py list W S E N start end [maxtile]
       s2.py get  W S E N item_id out.jpg
"""
import sys, os, json, numpy as np
os.environ.setdefault("AWS_NO_SIGN_REQUEST","YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN","EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY","4"); os.environ.setdefault("GDAL_HTTP_RETRY_DELAY","2")
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds
from pystac_client import Client
from PIL import Image
C=Client.open("https://earth-search.aws.element84.com/v1")
def crop(href,bbox,out_shape=None):
    with rasterio.open(href) as ds:
        b=transform_bounds("EPSG:4326",ds.crs,*bbox)
        w=from_bounds(*b,ds.transform).round_offsets().round_lengths()
        return ds.read(window=w,out_shape=out_shape,boundless=True,fill_value=0)
cmd=sys.argv[1]; bbox=tuple(map(float,sys.argv[2:6]))
if cmd=="list":
    s,e=sys.argv[6],sys.argv[7]; mx=float(sys.argv[8]) if len(sys.argv)>8 else 70
    items=list(C.search(collections=["sentinel-2-l2a"],bbox=bbox,datetime=f"{s}/{e}",query={"eo:cloud_cover":{"lt":mx}},max_items=200).items())
    res=[]
    for it in items:
        try:
            scl=crop(it.assets["scl"].href,bbox)[0]
            n=scl.size; nod=(scl==0).sum()/n
            cl=np.isin(scl,[3,8,9,10]).sum()/max(1,(scl!=0).sum())
            snow=(scl==11).sum()/max(1,(scl!=0).sum())
            res.append((it.id,it.datetime.date().isoformat(),round(it.properties["eo:cloud_cover"],1),round(cl*100,1),round(nod*100,1),round(snow*100,1)))
        except Exception as ex: print("err",it.id,ex,file=sys.stderr)
    for r in sorted(res,key=lambda r:r[1]): print(*r)
else:
    iid,out=sys.argv[6],sys.argv[7]
    it=next(C.search(collections=["sentinel-2-l2a"],ids=[iid]).items())
    a=crop(it.assets["visual"].href,bbox)
    img=Image.fromarray(np.moveaxis(a,0,-1))
    # gentle contrast: stretch 1-99 percentile per image
    img.save(out,quality=93)
    print(out,img.size,it.id,it.datetime.isoformat())
