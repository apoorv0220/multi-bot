const CURRENCY_SYMBOLS = {
  USD: '$',
  GBP: '£',
  EUR: '€',
  AUD: 'A$',
  CAD: 'C$',
  NZD: 'NZ$',
  INR: '₹',
  JPY: '¥',
  CNY: '¥',
  CHF: 'CHF ',
  SEK: 'kr ',
  NOK: 'kr ',
  DKK: 'kr ',
};

export function normalizeCurrencyCode(value) {
  const code = String(value || '').trim().toUpperCase();
  if (code.length === 3 && /^[A-Z]+$/.test(code)) {
    return code;
  }
  const aliases = {
    $: 'USD',
    'US$': 'USD',
    '£': 'GBP',
    'GB£': 'GBP',
    '€': 'EUR',
    EURO: 'EUR',
  };
  return aliases[code] || 'USD';
}

export function formatPrice(amount, currencyCode = 'USD') {
  const num = Number(amount);
  if (amount == null || Number.isNaN(num)) {
    return null;
  }
  const code = normalizeCurrencyCode(currencyCode);
  const symbol = CURRENCY_SYMBOLS[code];
  if (code === 'JPY') {
    const formatted = num.toLocaleString(undefined, { maximumFractionDigits: 0 });
    return symbol ? `${symbol}${formatted}` : `${code} ${formatted}`;
  }
  const formatted = num.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  if (symbol) {
    return symbol.endsWith(' ') ? `${symbol}${formatted}` : `${symbol}${formatted}`;
  }
  return `${code} ${formatted}`;
}
