# Match Status Logic (BLINKIT STATUS / JIO STATUS)

## Source
- Latest MRP from: https://mirror.apnamart.in/model/1808-latest-inward-cost-price
- LOOSE/ASM tagging from: https://mirror.apnamart.in/model/1344-product-master

## Status Definitions

### COMPLETE MATCH
- Same item (product matched correctly)
- Same unit value (AM unit_value == platform unit_value)
- Same MRP (AM MRP from model 1808 == platform MRP)

### SEMI COMPLETE MATCH
- Only for LOOSE/ASM items in STPLS master category
- Same unit (unit type matches — kg/kg, ml/ml etc.)
- MRP can be different

### PARTIAL MATCH
- Anything that doesn't meet COMPLETE or SEMI COMPLETE criteria
- Item matched but unit value OR MRP differs

### NA
- No match found on platform
- Product not available

## Warehouse Mapping (for MRP lookup)
- WRHS_1 = Jharkhand (Ranchi 834002, Hazaribagh 825301)
- WRHS_2 = Chhattisgarh (Raipur 492001)
- WRHS_10 = Kolkata (712232)
- WRHS_DURGAPOOR, WRHS_RANIGANJ, WRHS_ASANSOL = WB other cities

## Master Category Filter
Only include: STPLS, FMCG, FMCGF, FMCGNF, GM
