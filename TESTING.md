# Testing the development branch

Use a separate Streamlit Community Cloud app so production remains untouched.

## Deploy

- Repository: `MOTECHMIAMILLC/motech-price-list-manager`
- Branch: `development`
- Main file path: `app.py`
- Suggested app name: `motech-price-list-manager-dev`

## Internal operator checks

1. Open the normal app URL.
2. Upload current supplier Excel files.
3. Confirm invalid files are rejected rather than partially imported.
4. Verify the selected supplier is the lowest-cost eligible offer.
5. Open alternative suppliers and confirm stock, cost, MOQ and ETA.
6. Test a manual price override.
7. Hide and restore a product.
8. Add a manual product.
9. Review items under "Revisión requerida".
10. Publish an update.

## Public price list checks

Open the development URL with `?mode=public`.

Verify:
- interface is in English;
- product information is visible without a password;
- prices show as locked;
- Unlock Prices reveals prices after the correct password;
- public stock uses 20+ / 100+ rules;
- HOT DEAL, NEW ARRIVAL and LOW STOCK badges behave as expected;
- category and technical filters work.

## Safety

Do not merge PR #1 into `main` until the development deployment passes these checks.
