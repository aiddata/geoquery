# ESA Land Cover
ESA land cover class data product. Categories used are cropland (rainfed, irrigated, mosaic), forest, grassland, shrubland, sparse vegetation, wetland, urband, bare areas, water bodies, and snow ice.
UN Land Cover Classification System (LCCS) categories were grouped according to their IPCC classes, except for agriculture which was broken into 3 different types of cropland. The original land cover class names are modified in export file for readability and ease of use. The full name of each class can be found from land cover map user guide: https://cds.climate.copernicus.eu/cdsapp#!/dataset/satellite-land-cover. Version 2.0.7cds provides the LC maps for the years 1992-2015 and version 2.1.1 for the years after 2016 (both versions are produced with the same processing chain).
## Details
| | |
|---|---|
| Type | raster |
| Datetime | 2000-01-01 – 2002-01-01 |
| Temporal type | year |
| Tags | esa, landcover, environment |
| Variable | land cover class |

## Resources
| Name | Label | Date |
|---|---|---|
| esa_landcover_2000 | 2000 | 2000-01-01 |
| esa_landcover_2002 | 2002 | 2002-01-01 |

## Value Mappings
| Value | Label |
|---|---|
| 0 | no_data |
| 10 | rainfed_cropland |
| 20 | irrigated_cropland |
| 30 | mosaic_cropland |
| 50 | forest |
| 110 | grassland |
| 120 | shrubland |
| 140 | sparse_vegetation |
| 180 | wetland |
| 190 | urban |
| 200 | bare_areas |
| 210 | water_bodies |
| 220 | snow_ice |

## Citation
Defourny, P. (2017): ESA Land Cover Climate Change Initiative (Land_Cover_cci): Land Cover Maps, v2.0.7. Centre for Environmental Data Analysis, 7/2017
