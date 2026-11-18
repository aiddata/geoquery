---
description: "The boundary presets GeoQuery offers, which boundary sets each one includes, and the published list each one follows."
---

# Boundary presets

A boundary preset selects several boundary sets at once, such as the ADM1 boundaries of every country in Africa. Type a preset's name, or a short form like "LMIC", "SIDS" or "EU", in the boundary search on the Select Boundaries step, and choose it to add each of its boundary sets to your selection. Each set is then kept separate in your results, as when you select sets one by one (see [Selecting multiple boundary sets](../using-geoquery/multiple-boundaries.md)).

Presets are a shortcut for selecting boundaries. They don't change how data is extracted or summarized.

## Where membership comes from

Each preset follows a list published by an international organization, named below with a link. GeoQuery doesn't decide which countries or areas belong to a region or group. It applies the source's list as published, and uses the source's own names for each area. Lists from the UN's M49 standard were taken in November 2026.

In three places GeoQuery adds to or departs from a published list, so that every geoBoundaries boundary set belongs to a regional preset. Each is noted in its section:

- **North America** follows common English usage (the United States, Canada and Mexico) instead of the UN's "Northern America", which leaves out Mexico.
- **Central America** leaves out Mexico, which the UN also places in Central America.
- **Taiwan and Kosovo** are added to the Asia and Europe presets. The UN's M49 standard doesn't list either separately, but geoBoundaries publishes boundary sets for both.

Including or leaving out an area in a preset does not imply any opinion by AidData or William & Mary on the legal status of any country, territory or area, or on its borders. See the [map disclaimer](map-disclaimer.md).

## What a preset includes

Each preset is for one administrative level and lists the [geoBoundaries](https://www.geoboundaries.org) (version 6) boundary set for each member at that level. geoBoundaries doesn't publish every level for every area: many small territories have only a national (ADM0) boundary, for example. Where a member has no boundary set at a level, that level's preset leaves it out. The member lists below note these as "ADM0 only" or "no geoBoundaries set".

Member lists are split into UN member or observer states and other areas, following [UN membership](https://www.un.org/en/about-us/member-states). This describes each area's UN status only.

## Global presets

**Presets:** geoBoundaries ADM0, geoBoundaries ADM1, geoBoundaries ADM2
**Source:** every geoBoundaries version 6 boundary set at that level.

## Regions

### North America

**Presets:** North America ADM0, North America ADM1, North America ADM2
**Source:** GeoQuery's grouping: the United States, Canada and Mexico, as North America is commonly defined in English, plus the territories that the [UN M49 standard](https://unstats.un.org/unsd/methodology/m49/overview/) places in Northern America.

M49's "Northern America" leaves out Mexico, which it places in Central America.

??? note "Members: 3 UN member or observer states and 3 other areas"
    Canada; Mexico; United States of America.

    **Other areas:** Bermuda *(ADM0 only)*; Greenland *(ADM0, ADM1 only)*; Saint Pierre and Miquelon *(no geoBoundaries set)*.

### Central America

**Presets:** Central America ADM0, Central America ADM1, Central America ADM2
**Source:** GeoQuery's grouping: the seven countries of the Central American isthmus.

The [UN M49 standard](https://unstats.un.org/unsd/methodology/m49/overview/) also places Mexico in Central America; GeoQuery includes Mexico in North America instead.

??? note "Members: 7 UN member or observer states"
    Belize; Costa Rica; El Salvador; Guatemala; Honduras; Nicaragua; Panama.

### South America

**Presets:** South America ADM0, South America ADM1, South America ADM2
**Source:** The [UN M49 standard](https://unstats.un.org/unsd/methodology/m49/overview/) sub-region "South America".

??? note "Members: 12 UN member or observer states and 4 other areas"
    Argentina; Bolivia (Plurinational State of); Brazil; Chile; Colombia; Ecuador; Guyana; Paraguay; Peru; Suriname; Uruguay; Venezuela (Bolivarian Republic of).

    **Other areas:** Bouvet Island *(no geoBoundaries set)*; Falkland Islands (Malvinas) *(ADM0 only)*; French Guiana *(ADM0 only)*; South Georgia and the South Sandwich Islands *(no geoBoundaries set)*.

### Africa

**Presets:** Africa ADM0, Africa ADM1, Africa ADM2
**Source:** The [UN M49 standard](https://unstats.un.org/unsd/methodology/m49/overview/) region "Africa".

??? note "Members: 54 UN member or observer states and 6 other areas"
    Algeria; Angola; Benin; Botswana; Burkina Faso; Burundi; Cabo Verde; Cameroon; Central African Republic; Chad; Comoros; Congo; Côte d’Ivoire; Democratic Republic of the Congo; Djibouti; Egypt; Equatorial Guinea; Eritrea; Eswatini; Ethiopia; Gabon; Gambia; Ghana; Guinea; Guinea-Bissau; Kenya; Lesotho; Liberia; Libya *(ADM0, ADM1 only)*; Madagascar; Malawi; Mali; Mauritania; Mauritius *(ADM0, ADM1 only)*; Morocco; Mozambique; Namibia; Niger; Nigeria; Rwanda; Sao Tome and Principe; Senegal; Seychelles; Sierra Leone; Somalia; South Africa; South Sudan; Sudan; Togo; Tunisia; Uganda; United Republic of Tanzania; Zambia; Zimbabwe.

    **Other areas:** British Indian Ocean Territory *(no geoBoundaries set)*; French Southern Territories *(no geoBoundaries set)*; Mayotte *(ADM0 only)*; Réunion *(ADM0 only)*; Saint Helena *(ADM0 only)*; Western Sahara *(no geoBoundaries set)*.

### Asia

**Presets:** Asia ADM0, Asia ADM1, Asia ADM2
**Source:** The [UN M49 standard](https://unstats.un.org/unsd/methodology/m49/overview/) region "Asia".

M49 does not list Taiwan or Kosovo as separate areas. geoBoundaries publishes separate boundary sets for both, so GeoQuery includes them in the regional preset that covers their location, so that every geoBoundaries set falls in a regional preset.

??? note "Members: 48 UN member or observer states and 3 other areas"
    Afghanistan; Armenia; Azerbaijan; Bahrain *(ADM0, ADM1 only)*; Bangladesh; Bhutan; Brunei Darussalam; Cambodia; China; Cyprus; Democratic People's Republic of Korea; Georgia; India; Indonesia; Iran (Islamic Republic of); Iraq; Israel; Japan; Jordan; Kazakhstan; Kuwait; Kyrgyzstan; Lao People's Democratic Republic; Lebanon *(ADM1, ADM2 only)*; Malaysia; Maldives; Mongolia; Myanmar; Nepal; Oman; Pakistan; Philippines; Qatar; Republic of Korea; Saudi Arabia; Singapore; Sri Lanka; State of Palestine; Syrian Arab Republic; Tajikistan; Thailand; Timor-Leste; Turkmenistan; Türkiye; United Arab Emirates *(ADM0, ADM1 only)*; Uzbekistan; Viet Nam; Yemen.

    **Other areas:** China, Hong Kong Special Administrative Region *(no geoBoundaries set)*; China, Macao Special Administrative Region *(no geoBoundaries set)*; Taiwan.

### Europe

**Presets:** Europe ADM0, Europe ADM1, Europe ADM2
**Source:** The [UN M49 standard](https://unstats.un.org/unsd/methodology/m49/overview/) region "Europe".

M49 does not list Taiwan or Kosovo as separate areas. geoBoundaries publishes separate boundary sets for both, so GeoQuery includes them in the regional preset that covers their location, so that every geoBoundaries set falls in a regional preset.

??? note "Members: 44 UN member or observer states and 8 other areas"
    Albania; Andorra *(ADM0, ADM1 only)*; Austria; Belarus; Belgium; Bosnia and Herzegovina; Bulgaria; Croatia; Czechia; Denmark; Estonia; Finland; France; Germany; Greece; Holy See *(ADM0 only)*; Hungary; Iceland; Ireland; Italy; Latvia; Liechtenstein *(ADM0, ADM1 only)*; Lithuania; Luxembourg; Malta *(ADM0, ADM1 only)*; Monaco; Montenegro *(ADM0, ADM1 only)*; Netherlands (Kingdom of the); North Macedonia; Norway; Poland; Portugal; Republic of Moldova *(ADM0, ADM1 only)*; Romania; Russian Federation; San Marino *(ADM0, ADM1 only)*; Serbia; Slovakia; Slovenia; Spain; Sweden; Switzerland; Ukraine; United Kingdom of Great Britain and Northern Ireland.

    **Other areas:** Faroe Islands *(ADM0 only)*; Gibraltar *(ADM0 only)*; Guernsey *(ADM0 only)*; Isle of Man *(ADM0 only)*; Jersey *(no geoBoundaries set)*; Kosovo; Svalbard and Jan Mayen Islands *(no geoBoundaries set)*; Åland Islands *(no geoBoundaries set)*.

### Oceania

**Presets:** Oceania ADM0, Oceania ADM1, Oceania ADM2
**Source:** The [UN M49 standard](https://unstats.un.org/unsd/methodology/m49/overview/) region "Oceania".

??? note "Members: 14 UN member or observer states and 15 other areas"
    Australia; Fiji; Kiribati; Marshall Islands *(ADM0, ADM1 only)*; Micronesia (Federated States of); Naoero *(ADM0, ADM1 only)*; New Zealand; Palau; Papua New Guinea; Samoa; Solomon Islands; Tonga; Tuvalu; Vanuatu.

    **Other areas:** American Samoa *(ADM0 only)*; Christmas Island *(no geoBoundaries set)*; Cocos (Keeling) Islands *(no geoBoundaries set)*; Cook Islands *(ADM0 only)*; French Polynesia *(ADM0 only)*; Guam *(ADM0, ADM2 only)*; Heard Island and McDonald Islands *(no geoBoundaries set)*; New Caledonia *(ADM0 only)*; Niue *(ADM0, ADM1 only)*; Norfolk Island *(no geoBoundaries set)*; Northern Mariana Islands *(ADM0, ADM2 only)*; Pitcairn *(ADM0 only)*; Tokelau *(ADM0 only)*; United States Minor Outlying Islands *(no geoBoundaries set)*; Wallis and Futuna Islands *(ADM0 only)*.

### North Africa

**Presets:** North Africa ADM0, North Africa ADM1, North Africa ADM2
**Source:** The [UN M49 standard](https://unstats.un.org/unsd/methodology/m49/overview/) sub-region "Northern Africa".

??? note "Members: 6 UN member or observer states and 1 other area"
    Algeria; Egypt; Libya *(ADM0, ADM1 only)*; Morocco; Sudan; Tunisia.

    **Other areas:** Western Sahara *(no geoBoundaries set)*.

### Sub-Saharan Africa

**Presets:** Sub-Saharan Africa ADM0, Sub-Saharan Africa ADM1, Sub-Saharan Africa ADM2
**Source:** The [UN M49 standard](https://unstats.un.org/unsd/methodology/m49/overview/) sub-region "Sub-Saharan Africa".

??? note "Members: 48 UN member or observer states and 5 other areas"
    Angola; Benin; Botswana; Burkina Faso; Burundi; Cabo Verde; Cameroon; Central African Republic; Chad; Comoros; Congo; Côte d’Ivoire; Democratic Republic of the Congo; Djibouti; Equatorial Guinea; Eritrea; Eswatini; Ethiopia; Gabon; Gambia; Ghana; Guinea; Guinea-Bissau; Kenya; Lesotho; Liberia; Madagascar; Malawi; Mali; Mauritania; Mauritius *(ADM0, ADM1 only)*; Mozambique; Namibia; Niger; Nigeria; Rwanda; Sao Tome and Principe; Senegal; Seychelles; Sierra Leone; Somalia; South Africa; South Sudan; Togo; Uganda; United Republic of Tanzania; Zambia; Zimbabwe.

    **Other areas:** British Indian Ocean Territory *(no geoBoundaries set)*; French Southern Territories *(no geoBoundaries set)*; Mayotte *(ADM0 only)*; Réunion *(ADM0 only)*; Saint Helena *(ADM0 only)*.

## Development and political groupings

Membership of these groups changes over time. Each source below says when its list was taken, and the presets are updated when a source changes.

### Low and Middle Income Countries

**Presets:** Low and Middle Income Countries ADM0, Low and Middle Income Countries ADM1, Low and Middle Income Countries ADM2
**Source:** The [World Bank country classification by income](https://datahelpdesk.worldbank.org/knowledgebase/articles/906519): every economy classified as low income, lower-middle income or upper-middle income for the World Bank's fiscal year 2027 (published July 2026), as returned by the [World Bank API](https://api.worldbank.org/v2/country) on 18 November 2026.

The World Bank reclassifies economies every July. This preset will be updated to follow its classification.

??? note "Members: 130 UN member or observer states and 1 other area"
    Afghanistan; Albania; Algeria; Angola; Argentina; Armenia; Azerbaijan; Bangladesh; Belarus; Belize; Benin; Bhutan; Bolivia; Bosnia and Herzegovina; Botswana; Brazil; Burkina Faso; Burundi; Cabo Verde; Cambodia; Cameroon; Central African Republic; Chad; China; Colombia; Comoros; Congo, Dem. Rep.; Congo, Rep.; Cote d'Ivoire; Cuba; Djibouti; Dominica *(ADM0, ADM1 only)*; Dominican Republic; Ecuador; Egypt, Arab Rep.; El Salvador; Equatorial Guinea; Eritrea; Eswatini; Ethiopia; Fiji; Gabon; Gambia, The; Georgia; Ghana; Grenada *(ADM0, ADM1 only)*; Guatemala; Guinea; Guinea-Bissau; Haiti; Honduras; India; Indonesia; Iran, Islamic Rep.; Iraq; Jamaica; Jordan; Kazakhstan; Kenya; Kiribati; Korea, Dem. People's Rep.; Kyrgyz Republic; Lao PDR; Lebanon *(ADM1, ADM2 only)*; Lesotho; Liberia; Libya *(ADM0, ADM1 only)*; Madagascar; Malawi; Malaysia; Maldives; Mali; Marshall Islands *(ADM0, ADM1 only)*; Mauritania; Mauritius *(ADM0, ADM1 only)*; Mexico; Micronesia, Fed. Sts.; Moldova *(ADM0, ADM1 only)*; Mongolia; Montenegro *(ADM0, ADM1 only)*; Morocco; Mozambique; Myanmar; Namibia; Nepal; Nicaragua; Niger; Nigeria; North Macedonia; Pakistan; Papua New Guinea; Paraguay; Peru; Philippines; Rwanda; Samoa; Sao Tome and Principe; Senegal; Serbia; Sierra Leone; Solomon Islands; Somalia, Fed. Rep.; South Africa; South Sudan; Sri Lanka; St. Lucia; St. Vincent and the Grenadines *(ADM0, ADM1 only)*; Sudan; Suriname; Syrian Arab Republic; Tajikistan; Tanzania; Thailand; Timor-Leste; Togo; Tonga; Tunisia; Turkiye; Turkmenistan; Tuvalu; Uganda; Ukraine; Uzbekistan; Vanuatu; Venezuela, RB; Viet Nam; West Bank and Gaza; Yemen, Rep.; Zambia; Zimbabwe.

    **Other areas:** Kosovo.

### Small Island Developing States

**Presets:** Small Island Developing States ADM0, Small Island Developing States ADM1, Small Island Developing States ADM2
**Source:** The Small Island Developing States marked in the [UN M49 standard](https://unstats.un.org/unsd/methodology/m49/overview/), including the territories it lists.

The UN Office of the High Representative for the Least Developed Countries, Landlocked Developing Countries and Small Island Developing States ([UN-OHRLLS](https://www.un.org/ohrlls/content/list-sids)) publishes its own list, which can differ slightly from M49's. For example, it includes Bahrain.

??? note "Members: 37 UN member or observer states and 16 other areas"
    Antigua and Barbuda *(ADM0, ADM1 only)*; Bahamas; Barbados *(ADM0, ADM1 only)*; Belize; Cabo Verde; Comoros; Cuba; Dominica *(ADM0, ADM1 only)*; Dominican Republic; Fiji; Grenada *(ADM0, ADM1 only)*; Guinea-Bissau; Guyana; Haiti; Jamaica; Kiribati; Maldives; Marshall Islands *(ADM0, ADM1 only)*; Mauritius *(ADM0, ADM1 only)*; Micronesia (Federated States of); Naoero *(ADM0, ADM1 only)*; Palau; Papua New Guinea; Saint Kitts and Nevis *(ADM0, ADM1 only)*; Saint Lucia; Saint Vincent and the Grenadines *(ADM0, ADM1 only)*; Samoa; Sao Tome and Principe; Seychelles; Singapore; Solomon Islands; Suriname; Timor-Leste; Tonga; Trinidad and Tobago *(ADM0, ADM1 only)*; Tuvalu; Vanuatu.

    **Other areas:** American Samoa *(ADM0 only)*; Anguilla *(ADM0 only)*; Aruba *(ADM0 only)*; Bonaire, Sint Eustatius and Saba *(ADM0 only)*; British Virgin Islands *(ADM0 only)*; Cook Islands *(ADM0 only)*; Curaçao *(ADM0 only)*; French Polynesia *(ADM0 only)*; Guam *(ADM0, ADM2 only)*; Montserrat *(ADM0 only)*; New Caledonia *(ADM0 only)*; Niue *(ADM0, ADM1 only)*; Northern Mariana Islands *(ADM0, ADM2 only)*; Puerto Rico *(ADM2 only)*; Sint Maarten (Dutch part) *(no geoBoundaries set)*; United States Virgin Islands *(ADM0 only)*.

### European Union

**Presets:** European Union ADM0, European Union ADM1, European Union ADM2
**Source:** The 27 member states of the [European Union](https://european-union.europa.eu/principles-countries-history/eu-countries_en), as of November 2026.

Some areas outside Europe are legally part of the EU, such as France's overseas regions. geoBoundaries publishes some of them as separate boundary sets, which this preset does not include.

??? note "Members: 27 UN member or observer states"
    Austria; Belgium; Bulgaria; Croatia; Cyprus; Czechia; Denmark; Estonia; Finland; France; Germany; Greece; Hungary; Ireland; Italy; Latvia; Lithuania; Luxembourg; Malta *(ADM0, ADM1 only)*; Netherlands (Kingdom of the); Poland; Portugal; Romania; Slovakia; Slovenia; Spain; Sweden.

## Suggest a preset

To suggest a preset, or to report a preset that no longer matches its source, open an issue on [GitHub](https://github.com/aiddata/geoquery/issues).
