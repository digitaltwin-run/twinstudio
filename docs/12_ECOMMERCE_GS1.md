# 12 — Ecommerce and GS1/GTIN

## Commercial object

An `EcommerceOffer` links:

- SKU;
- GTIN value and assignment status;
- title and description;
- price/currency/tax category;
- stock state;
- media artifacts;
- package object;
- channel attributes.

The offer is a project object so claims can be traced to technical evidence and approved revisions.

## GTIN versus EAN

“EAN” is commonly used for the retail barcode representation, while the product identifier is managed as a GTIN. The included utility can calculate/validate the final check digit for a provided number body. It cannot assign an authorized company prefix or product reference.

Do not publish a generated demo number as a real product identifier. The product owner must allocate the identifier through its GS1 licensing/assignment process and record evidence/status in the project.

## Listing generation

An LLM may draft channel-specific copy from approved project facts, but it must not invent compliance, performance or compatibility claims. A listing generator should:

1. select an approved product revision;
2. read only approved claims/requirements/test evidence;
3. generate title, bullets, description and attributes;
4. mark uncertain/missing fields;
5. validate package dimensions, included items, SKU and GTIN status;
6. require commercial/legal approval;
7. attach the final listing and marketplace response as artifacts/events.

## Future integrations

- product information management systems;
- marketplace APIs;
- inventory/ERP;
- price and quotation history;
- digital product passport and service documentation;
- warranty/returns feedback feeding FMEA and future revisions.
