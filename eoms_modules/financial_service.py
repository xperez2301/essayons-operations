def clean(value):
    return "" if value is None else str(value).strip()


def num(value, default=0):
    try:
        if value in [None, ""]:
            return default
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


class FinancialService:
    def __init__(
        self,
        rate_per_piece=0.95,
        driver_pay_per_piece=0.30,
        pieces_per_rack=19,
    ):
        self.rate_per_piece = rate_per_piece
        self.driver_pay_per_piece = driver_pay_per_piece
        self.pieces_per_rack = pieces_per_rack

    def expected_racks(self, item):
        return num(item.get("expected_racks"))

    def expected_pieces(self, item):
        pieces = num(item.get("expected_pieces"))
        if pieces:
            return pieces
        return self.expected_racks(item) * self.pieces_per_rack

    def revenue_for_item(self, item):
        return round(self.expected_pieces(item) * self.rate_per_piece, 2)

    def driver_pay_for_item(self, item):
        return round(self.expected_pieces(item) * self.driver_pay_per_piece, 2)

    def potential_revenue(self, stores):
        ready = [
            s for s in stores
            if clean(s.get("status")) in {"Unassigned", "Ready to Route"}
        ]
        return round(sum(self.revenue_for_item(s) for s in ready), 2)

    def driver_payroll_estimate(self, stores):
        return round(sum(self.driver_pay_for_item(s) for s in stores), 2)

    def estimated_profit(self, stores):
        revenue = sum(self.revenue_for_item(s) for s in stores)
        payroll = sum(self.driver_pay_for_item(s) for s in stores)
        return round(revenue - payroll, 2)

    def dashboard_financials(self, stores):
        return {
            "potential_revenue": self.potential_revenue(stores),
            "estimated_driver_payroll": self.driver_payroll_estimate(stores),
            "estimated_profit": self.estimated_profit(stores),
        }


financials = FinancialService()