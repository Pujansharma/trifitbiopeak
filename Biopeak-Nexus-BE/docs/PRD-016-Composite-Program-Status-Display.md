# Composite Program Status Display — ePRD

Authenticated endpoints use Bearer tokens.

## Logical Flow

1. Read the flags from the composite program object, or from `program` when a service response includes parent status.
2. Show exactly one label using the first matching row below.
3. Refresh the program after a successful classification edit or payment.

## Display Precedence

| First matching condition | Display |
| --- | --- |
| `is_part_of_package=true` | Part of package |
| Otherwise, `is_complimentary=true` | Complimentary |
| Otherwise, `is_credit=true` | On credit |
| Otherwise | Paid Status |

`is_part_of_package=false` has no label of its own. Continue checking both existing flags; complimentary false alone does not imply paid when credit is true. If the package field is absent, use the existing flags.

Relevant response fields for a new composite created without classification keys:

```json
{
  "is_part_of_package": true,
  "is_complimentary": false,
  "is_credit": false
}
```

Display **Part of package** for this example. The package marker takes precedence over both classification flags.

## Field Behavior

- `is_part_of_package` is read-only and returned only for composite Programs, including nested Program status objects. Do not send it as input.
- On creation, omit both `is_complimentary` and `is_credit` to start with `is_part_of_package=true`, `is_complimentary=false`, and `is_credit=false`. Lead conversion uses the same values. Explicitly supplying either classification key, including false, starts the marker false.
- Assignment and unrelated edits allow no price while the marker remains true. Supplying either classification key clears that exemption; non-complimentary programs then require a price under the usual rules. Payments still require a stored price.
- A successful composite PATCH or assigned therapy-service PATCH supplying either classification key clears the marker, even when the supplied value is unchanged. It stays false afterward.
- A successful composite payment supplying either key also clears it; payment still does not change the stored classification flags. Payment without these keys preserves it.
- Unrelated edits preserve the marker. Failed operations leave it unchanged.

Use the API name `is_credit` for **On credit**. There is no `is_paid` or `is_on_credit` field.
