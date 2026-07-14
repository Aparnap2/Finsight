def query_vendor_invoices(vendor_name: str, period: str) -> list[dict]:
    return [{"vendor": vendor_name, "period": period, "amount": 80000}]
