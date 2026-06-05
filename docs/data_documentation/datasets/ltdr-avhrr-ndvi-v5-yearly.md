# Yearly Normalized Difference Vegetation Index - NDVI (LTDR v5 - AVHRR)
Yearly value for Normalized Difference Vegetation Index (NDVI). Created using the NASA Long Term Data Record (v5) AVHRR data.
Created by aggregating daily data to monthly by taking the maximum value, then averaging the monthly data to get yearly values. All negative NDVI values were truncated to 0 and saturated pixels were adjusted to the max of the normal NDVI range (10000).
## Details
| | |
|---|---|
| Type | raster |
| Datetime | 2010-01-01 – 2020-01-01 |
| Temporal type | year |
| Tags | nasa, ltdr, ndvi, avhrr, vegetation, environment |
| Variable | positive NDVI values 0:10000 (factor: 10000.0) |

## Resources
| Name | Label | Date |
|---|---|---|
| ltdr_avhrr_ndvi_v5_yearly_2010 | 2010 | 2010-01-01 |
| ltdr_avhrr_ndvi_v5_yearly_2020 | 2020 | 2020-01-01 |

## Citation
Pedelty JA, Devadiga S, Masuoka E et al. (2007) Generating a Long-term Land Data Record from the AVHRR and MODIS Instruments. Proceedings of IGARRS 2007, pp. 1021–1025. Institute of Electrical and Electronics Engineers, NY, USA.
