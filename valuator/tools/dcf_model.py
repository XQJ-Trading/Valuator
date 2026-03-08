from __future__ import annotations

import json
from typing import Any

_DCF_CALCULATION_RUNTIME = """
base_revenue = float(assumptions['base_revenue'])
base_growth = float(assumptions['growth_rate'])
base_op_margin = float(assumptions['op_margin'])
base_tax_rate = float(assumptions['tax_rate'])
base_reinvestment_rate = float(assumptions['reinvestment_rate'])
base_discount_rate = float(assumptions['discount_rate'])
base_terminal_growth = float(assumptions['terminal_growth'])
years = max(1, int(assumptions['projection_years']))

def clamp(value, lower, upper):
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value

def adjust_terminal_growth(discount_rate, terminal_growth):
    max_terminal = discount_rate - 0.002
    if terminal_growth > max_terminal:
        return max_terminal
    return terminal_growth

def build_case_params(growth_rate, op_margin, tax_rate, reinvestment_rate, discount_rate, terminal_growth):
    growth_rate = clamp(float(growth_rate), -0.95, 2.0)
    op_margin = clamp(float(op_margin), 0.0, 1.0)
    tax_rate = clamp(float(tax_rate), 0.0, 0.8)
    reinvestment_rate = clamp(float(reinvestment_rate), 0.0, 1.5)
    discount_rate = clamp(float(discount_rate), 0.001, 1.5)
    terminal_growth = clamp(float(terminal_growth), -0.95, 1.0)
    terminal_growth = adjust_terminal_growth(discount_rate, terminal_growth)
    return {
        'growth_rate': growth_rate,
        'op_margin': op_margin,
        'tax_rate': tax_rate,
        'reinvestment_rate': reinvestment_rate,
        'discount_rate': discount_rate,
        'terminal_growth': terminal_growth,
        'projection_years': years,
    }

def compute_case_metrics(case_params):
    growth_rate = case_params['growth_rate']
    op_margin = case_params['op_margin']
    tax_rate = case_params['tax_rate']
    reinvestment_rate = case_params['reinvestment_rate']
    discount_rate = case_params['discount_rate']
    terminal_growth = case_params['terminal_growth']

    fcff = []
    revenue = base_revenue
    for _ in range(years):
        revenue = revenue * (1 + growth_rate)
        ebit = revenue * op_margin
        nopat = ebit * (1 - tax_rate)
        reinvest = nopat * reinvestment_rate
        fcff.append(nopat - reinvest)

    pv_explicit = 0.0
    for idx, cash in enumerate(fcff, start=1):
        pv_explicit += cash / ((1 + discount_rate) ** idx)

    terminal_cash = fcff[-1] * (1 + terminal_growth)
    spread = discount_rate - terminal_growth
    if spread <= 0.0001:
        spread = 0.0001
    terminal_value = terminal_cash / spread
    terminal_pv = terminal_value / ((1 + discount_rate) ** years)
    enterprise_value = pv_explicit + terminal_pv

    return {
        'pv_explicit': pv_explicit,
        'terminal_value': terminal_value,
        'terminal_pv': terminal_pv,
        'enterprise_value': enterprise_value,
        'fcff_series': fcff,
    }

base_case_params = build_case_params(
    base_growth,
    base_op_margin,
    base_tax_rate,
    base_reinvestment_rate,
    base_discount_rate,
    base_terminal_growth,
)

bull_case_params = build_case_params(
    base_growth * 1.15,
    base_op_margin * 1.10,
    base_tax_rate,
    base_reinvestment_rate * 0.95,
    base_discount_rate - 0.01,
    base_terminal_growth + 0.005,
)

bear_case_params = build_case_params(
    base_growth * 0.85,
    base_op_margin * 0.90,
    base_tax_rate,
    base_reinvestment_rate * 1.05,
    base_discount_rate + 0.01,
    base_terminal_growth - 0.005,
)

scenarios = {
    'base': {'assumptions': base_case_params, **compute_case_metrics(base_case_params)},
    'bull': {'assumptions': bull_case_params, **compute_case_metrics(bull_case_params)},
    'bear': {'assumptions': bear_case_params, **compute_case_metrics(bear_case_params)},
}

base_enterprise_value = scenarios['base']['enterprise_value']
for _, scenario in scenarios.items():
    if base_enterprise_value == 0:
        scenario['ev_vs_base_pct'] = 0.0
    else:
        scenario['ev_vs_base_pct'] = ((scenario['enterprise_value'] / base_enterprise_value) - 1.0) * 100.0

wacc_offsets = [-0.01, 0.0, 0.01]
growth_offsets = [-0.01, 0.0, 0.01]
wacc_values = [clamp(base_case_params['discount_rate'] + offset, 0.001, 1.5) for offset in wacc_offsets]
growth_values = [clamp(base_case_params['growth_rate'] + offset, -0.95, 2.0) for offset in growth_offsets]
sensitivity_rows = []
for growth_rate in growth_values:
    row = {'growth_rate': growth_rate, 'enterprise_values': []}
    for wacc in wacc_values:
        point_case = build_case_params(
            growth_rate,
            base_case_params['op_margin'],
            base_case_params['tax_rate'],
            base_case_params['reinvestment_rate'],
            wacc,
            base_case_params['terminal_growth'],
        )
        point_metrics = compute_case_metrics(point_case)
        row['enterprise_values'].append(point_metrics['enterprise_value'])
    sensitivity_rows.append(row)

wacc_down_case = build_case_params(
    base_case_params['growth_rate'],
    base_case_params['op_margin'],
    base_case_params['tax_rate'],
    base_case_params['reinvestment_rate'],
    base_case_params['discount_rate'] - 0.01,
    base_case_params['terminal_growth'],
)
wacc_up_case = build_case_params(
    base_case_params['growth_rate'],
    base_case_params['op_margin'],
    base_case_params['tax_rate'],
    base_case_params['reinvestment_rate'],
    base_case_params['discount_rate'] + 0.01,
    base_case_params['terminal_growth'],
)
growth_down_case = build_case_params(
    base_case_params['growth_rate'] - 0.01,
    base_case_params['op_margin'],
    base_case_params['tax_rate'],
    base_case_params['reinvestment_rate'],
    base_case_params['discount_rate'],
    base_case_params['terminal_growth'],
)
growth_up_case = build_case_params(
    base_case_params['growth_rate'] + 0.01,
    base_case_params['op_margin'],
    base_case_params['tax_rate'],
    base_case_params['reinvestment_rate'],
    base_case_params['discount_rate'],
    base_case_params['terminal_growth'],
)

wacc_down_ev = compute_case_metrics(wacc_down_case)['enterprise_value']
wacc_up_ev = compute_case_metrics(wacc_up_case)['enterprise_value']
growth_down_ev = compute_case_metrics(growth_down_case)['enterprise_value']
growth_up_ev = compute_case_metrics(growth_up_case)['enterprise_value']

wacc_max_abs_delta = max(abs(wacc_down_ev - base_enterprise_value), abs(wacc_up_ev - base_enterprise_value))
growth_max_abs_delta = max(abs(growth_down_ev - base_enterprise_value), abs(growth_up_ev - base_enterprise_value))
most_impactful_variable = 'discount_rate' if wacc_max_abs_delta >= growth_max_abs_delta else 'growth_rate'

result = {
    'pv_explicit': scenarios['base']['pv_explicit'],
    'terminal_value': scenarios['base']['terminal_value'],
    'terminal_pv': scenarios['base']['terminal_pv'],
    'enterprise_value': scenarios['base']['enterprise_value'],
    'fcff_series': scenarios['base']['fcff_series'],
    'scenarios': scenarios,
    'sensitivity': {
        'axes': {
            'wacc': wacc_values,
            'growth_rate': growth_values,
        },
        'table': sensitivity_rows,
        'impact': {
            'discount_rate': {
                'base': base_case_params['discount_rate'],
                'minus_100bp_ev': wacc_down_ev,
                'plus_100bp_ev': wacc_up_ev,
                'max_abs_delta_vs_base_ev': wacc_max_abs_delta,
            },
            'growth_rate': {
                'base': base_case_params['growth_rate'],
                'minus_100bp_ev': growth_down_ev,
                'plus_100bp_ev': growth_up_ev,
                'max_abs_delta_vs_base_ev': growth_max_abs_delta,
            },
            'most_impactful_variable': most_impactful_variable,
        },
    },
}
print(result)
""".strip()


def build_dcf_calculation_code(*, assumptions: dict[str, Any]) -> str:
    assumptions_payload = json.dumps(assumptions, ensure_ascii=False)
    return f"assumptions = {assumptions_payload}\n{_DCF_CALCULATION_RUNTIME}\n"
