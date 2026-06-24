<!--
=============================================================================
MAINTENANCE GUIDANCE — for future agents/editors updating this page
=============================================================================
PURPOSE
  A curated showcase of research that cites GeoQuery, organized by topic to
  demonstrate the tool's breadth. It is intentionally NOT exhaustive.

HOW TO REFRESH (the citing-works list)
  1. The canonical source is the Google Scholar "cited by" search linked in
     the intro (the three `cites=` IDs are the GeoQuery paper's cluster IDs —
     do not change them). Sort by relevance to find newly well-cited work;
     sort by date (append `&scisbd=1` to the URL) to find the newest work.
  2. Watch for FALSE POSITIVES: a separate, classic NLP/semantic-parsing
     dataset is also named "GeoQuery." Papers about text-to-SQL, LLM query
     parsing, or SQL autograding almost always cite THAT one, not AidData's
     tool. Exclude them.
  3. Prefer breadth over volume: aim to cover each topical section, giving
     some priority to influential / highly-cited work. Trim weakest entries
     rather than letting any one section balloon.
  4. Revisit the SECTION STRUCTURE itself, not just the entries. The current
     topical sections reflect where citing work clustered at the time of
     writing — as the body of research evolves, consider whether to add a new
     section for an emerging theme, merge or rename sections that no longer
     fit, split one that has grown too broad, or reorder them. The structure
     should serve the current literature, not be preserved for its own sake.

PER-ENTRY CONVENTIONS
  - Format: `[**Title**](link) — Author, A., Author, B. (Year). *Venue.*
    Optional one-line description.`
  - Link the title to the most stable canonical source, preferring in order:
    publisher DOI (https://doi.org/...) > publisher article page > stable
    repository (RePEc/institutional) for working papers.
  - VERIFY metadata against the source, not just the Scholar snippet —
    Scholar mislabels venues (e.g., a working paper later published in a
    journal, or a wrong journal name). Fix venue/year when you confirm them.
  - Do NOT include "Cited by N" counts; they go stale quickly and were
    deliberately removed.

KEEP THIS GUIDANCE CURRENT
  If you change the conventions above (formatting, what to link, sourcing
  rules), update this comment to match. If a rule here no longer applies,
  remove it. Leave the comment in place for the next editor.
=============================================================================
-->

# GeoQuery Research and Use Cases

GeoQuery makes it easy for researchers to extract, aggregate, and download geospatial
data summarized to administrative boundaries and other units of analysis — without
needing GIS expertise or high-performance computing access. Since its release, it has
been cited in research across economics, political science, environmental science,
public health, and geospatial methods.

This page highlights a selection of peer-reviewed studies and datasets that have used or
built on GeoQuery. It is not a complete list of the ~190 works that cite GeoQuery, but
is curated to show the breadth of topics the tool supports, with priority given to
influential, well-cited work.

> Goodman, S., BenYishay, A., Lv, Z., & Runfola, D. (2019).
> [GeoQuery: Integrating HPC systems and public web-based geospatial data tools](https://doi.org/10.1016/j.cageo.2018.10.009).
> *Computers & Geosciences*, 122, 103–112.

For citation guidance, see [Citing GeoQuery](citing.md).

For the complete list of works citing GeoQuery, visit [Google Scholar](https://scholar.google.com/scholar?oi=bibs&hl=en&cites=2560106665827083734,12106762631401982756,10858659470229376865)

---

## Foundational data and methods

GeoQuery sits within a wider ecosystem of open geospatial data resources and machine
learning methods developed by AidData and collaborators.

- [**geoBoundaries: A global database of political administrative boundaries**](https://doi.org/10.1371/journal.pone.0231866)
  — Runfola, D., Anderson, A., Baier, H., Crittenden, M., et al. (2020). *PLOS ONE.* An open-license
  resource for the geographic boundaries of political administrative divisions worldwide,
  widely used alongside GeoQuery for aggregation units.
- [**AidData's geospatial global Chinese development finance dataset**](https://doi.org/10.1038/s41597-024-03341-w)
  — Goodman, S., Zhang, S., Malik, A. A., Parks, B. C., Hall, J., et al. (2024). *Scientific Data.*
  Detailed geocoded information on more than 20,000 development projects across 165
  countries.
- [**GLocal: A global development dataset of subnational administrative areas**](https://doi.org/10.1038/s41597-024-03539-y)
  — Morales-Arilla, J., & Gadgin Matha, S. (2024). *Scientific Data.* A dataset enabling
  development research that requires both global scope and local precision.
- [**A multi-glimpse deep learning architecture to estimate socioeconomic census metrics
  in the context of extreme scope variance**](https://doi.org/10.1080/13658816.2024.2305636)
  — Runfola, D., Stefanidis, A., Lv, Z., O'Brien, J., et al. (2024). *International Journal of Geographical Information Science.*
  CNNs applied to satellite imagery for estimating aggregated socioeconomic information.
- [**Spatiotemporal prediction of conflict fatality risk using convolutional neural
  networks and satellite imagery**](https://doi.org/10.3390/rs16183411)
  — Goodman, S., BenYishay, A., & Runfola, D. (2024). *Remote Sensing.* Image-based machine learning for forecasting conflict risk.

---

## Development finance and foreign aid

A major use of GeoQuery is in subnational analysis of aid allocation and the impacts of
development projects.

- [**Impact of official development assistance projects for renewable energy on
  electrification in sub-Saharan Africa**](https://doi.org/10.1016/j.worlddev.2021.105784)
  — Chapel, C. (2022). *World Development.*
- [**Highway to the forest? Land governance and the siting and environmental impacts of
  Chinese government-funded road building in Cambodia**](https://doi.org/10.1016/j.jeem.2023.102898)
  — Baehr, C., BenYishay, A., & Parks, B. (2023). *Journal of Environmental Economics and Management.*
- [**Does India use development finance to compete with China? A subnational
  analysis**](https://doi.org/10.1177/00220027241228184) — Asmus, G., Eichenauer, V.,
  Fuchs, A., & Parks, B. (2025). *Journal of Conflict Resolution.*
- [**The economic efficiency of aid targeting**](https://doi.org/10.1016/j.worlddev.2022.106062)
  — BenYishay, A., DiLorenzo, M., & Dolan, C. (2022). *World Development.*
- [**International politics and the subnational allocation of World Bank development
  projects**](https://doi.org/10.1177/14789299231153821) — DiLorenzo, M. (2023). *Political Studies Review.*
- [**Spatial interdependence and spillovers of fiscal grants in Benin**](https://doi.org/10.1016/j.worlddev.2022.106006)
  — Vincent, R. C., & Kwadwo, V. O. (2022). *World Development.*

---

## Conflict, violence, and peacekeeping

- [**Floods, communal conflict and the role of local state institutions in Sub-Saharan
  Africa**](https://doi.org/10.1016/j.polgeo.2021.102511) — Petrova, K. (2022). *Political
  Geography.* Examines whether flood disasters increase communal conflict risk and how
  state trust mitigates the effect.
- [**Nationality, gender, and deployments at the local level: Introducing the RADPKO
  dataset**](https://doi.org/10.1080/13533312.2020.1738228) — Hunnicutt, P., & Nomikos,
  W. G. (2020). *International Peacekeeping.* A new dataset of geocoded United Nations
  peacekeeping deployments in Africa.
- [**Access to toilets and violence against women**](https://doi.org/10.1016/j.jeem.2022.102695)
  — Hossain, M. A., Mahajan, K., & Sekhri, S. (2022). *Journal of Environmental Economics
  and Management.* Uses India's Swachh Bharat Mission data.
- [**Food-related violence, hunger and humanitarian crises**](https://doi.org/10.1177/00223433221099309)
  — Dowd, C. (2023). *Journal of Peace Research.*

---

## Environment, land use, and climate

<!-- TODO: title left unlinked — DOI not yet verified. If you confirm it
     (Land Degradation & Development, 2021, vol. 32, 946–964), wrap the title
     in a link and remove this note. -->
- **Which impacts more seriously on natural habitat loss and degradation? Cropland
  expansion or urban expansion?** — Tang, L., Ke, X., Chen, Y., Wang, L., Zhou, Q., et al.
  (2021). *Land Degradation & Development.*
- [**The LANDSUPPORT geospatial decision support system (S-DSS) vision**](https://doi.org/10.1002/ldr.4954)
  — Terribile, F., Acutis, M., Agrillo, A., et al. (2024). *Land Degradation &
  Development.* Operational tools to implement sustainability policies in land planning
  and management.
- [**Riders on the storm: How do firms navigate production and market conditions amid El
  Niño?**](https://doi.org/10.1016/j.jdeveco.2024.103374) — Bas, M., & Paunov, C. (2025).
  *Journal of Development Economics.*
- [**Which exerts a greater impact on ecosystem resilience: Cropland expansion or urban
  expansion?**](https://www.sciencedirect.com/science/article/pii/S1574954125003231) —
  Wu, J., Wang, H., Wang, C., Huang, X., et al. (2025). *Ecological Informatics.*
- [**The sustainable use of soils: A journey from wicked problems to wicked solutions for
  soil policy**](https://www.sciencedirect.com/science/article/pii/S2667006224000480) —
  Terribile, F., Basile, A., Bonifacio, E., Corti, G., et al. (2024). *Soil Security.*
- [**Assessing climate change effects on the gendered productivity gap for smallholder
  farming in Mali**](https://doi.org/10.1007/s10113-025-02444-3) — Sangaré, B., Singbo,
  A., & Tamini, L. D. (2025). *Regional Environmental Change.*

---

## Economic measurement, nighttime lights, and poverty

- [**Open Earth observations for sustainable urban development**](https://doi.org/10.3390/rs12101646)
  — Prakash, M., Ramage, S., Kavvada, A., Goodman, S., et al. (2020). *Remote Sensing.*
- [**Research deserts and oases: evidence from 27 thousand economics journal articles on
  Africa**](https://doi.org/10.1111/obes.12510) — Porteous, O. (2022). *Oxford Bulletin
  of Economics and Statistics.* Maps the highly uneven distribution of economics research
  across Africa.
- [**Estimating urban GDP growth using nighttime lights and machine learning techniques in
  data poor environments: the case of South Sudan**](https://doi.org/10.1016/j.techfore.2024.123399)
  — McSharry, P., & Mawejje, J. (2024). *Technological Forecasting and Social Change.*
- [**The impact of special economic zones on economic development: evidence from nightlight
  analysis in the Lao People's Democratic Republic**](https://doi.org/10.1142/S0116110524400109)
  — Phommachanh, N. (2024). *Asian Development Review.*
- [**Estimation of the sub-national fiscal potential of WAEMU countries using satellite
  images of nighttime lights data**](https://elar.urfu.ru/handle/10995/148743) — Lawin,
  M. L. (2025). *Journal of Tax Reform.*

---

## Governance, public services, and state capacity

- [**When does transparency improve public services? Street-level discretion, information,
  and targeting**](https://doi.org/10.1111/padm.12693) — Bauhr, M., & Carlitz, R. (2021).
  *Public Administration.*
- [**Who are the health workers and where are they? Revealed preferences in location
  decision among health care professionals in the Philippines**](https://pids.gov.ph/publication/discussion-papers/who-are-the-health-workers-and-where-are-they-revealed-preferences-in-location-decision-among-health-care-professionals-in-the-philippines)
  — Abrigo, M. R. M., & Ortiz, D. A. P. (2019).
- [**Ethnic diversity and local economies**](https://doi.org/10.1111/saje.12286) — Dinku,
  Y., & Regasa, D. (2021). *South African Journal of Economics.*
- [**Technology and the state: Building capacity to tax via text**](https://doi.org/10.1016/j.jpubeco.2024.105139)
  — Cohen, I. (2024). *Journal of Public Economics.*
- [**Documenting decentralization: Empirical evidence on administrative unit proliferation
  from Uganda**](https://doi.org/10.1093/wber/lhae008) — Cohen, I. (2024). *The World Bank
  Economic Review.*

---

## Agriculture, energy, health, and livelihoods

- [**Household dependence on solid cooking fuels in Peru: an analysis of environmental and
  socioeconomic conditions**](https://doi.org/10.1016/j.gloenvcha.2019.101961) — McLean,
  E. V., Bagchi-Sen, S., Atkinson, J. D., et al. (2019). *Global Environmental Change.*
- [**The impact of livelihood diversification as a climate change adaptation strategy on
  poverty level of pastoral households in southeastern and southern Ethiopia**](https://doi.org/10.1080/23311886.2023.2277349)
  — Beyene, B., Tilahun, M., & Alemu, M. (2023). *Cogent Social Sciences.*
- [**Training, credit, and infrastructure for improving market access among small-scale
  producers in the Philippines**](https://doi.org/10.1016/j.foodpol.2025.102853) —
  Hossain, M., Mendiratta, V., Mabiso, A., & Songsermsawas, T. (2025). *Food Policy.*
- [**Bridging the digital divide: How 3G internet coverage transforms fertility decisions
  in Nigeria**](https://ideas.repec.org/p/ags/aaea25/360944.html) — Gao, Y., Mullally, C.,
  Ji, X. J., & Gars, J. (2025).
- [**Eradicating the disease of the empty granary**](https://ideas.repec.org/p/unu/wpaper/wp-2025-111.html)
  — Carney, C. O., & Denton-Schneider, J. (2025). *UNU-WIDER.* Examines guinea worm
  disease's effects on agricultural productivity.

---

*This list is maintained by the GeoQuery team and reflects a snapshot of citing work
indexed on Google Scholar. To suggest an addition, contact
[geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu).*
