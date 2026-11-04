// Illustrative demo fixtures. They are NOT sourced from your PostgreSQL database.
export const customers = [
  { id: 10021, name: 'Aarav Mehta', initials: 'AM', city: 'Mumbai', score: 91, income: 145000, creditScore: 812, balance: 380000, product: 'Premium Personal Loan', code: 'PL_PREMIUM', reason: 'Strong salary inflows, excellent credit and low existing EMI burden', contacted: 'Never', consent: true },
  { id: 10047, name: 'Priya Nair', initials: 'PN', city: 'Pune', score: 87, income: 118000, creditScore: 795, balance: 245000, product: 'Premium Personal Loan', code: 'PL_PREMIUM', reason: 'Stable monthly salary, healthy balance and previous loan interest', contacted: '62 days ago', consent: true },
  { id: 10063, name: 'Rohan Desai', initials: 'RD', city: 'Bengaluru', score: 82, income: 97000, creditScore: 778, balance: 182000, product: 'Premium Personal Loan', code: 'PL_PREMIUM', reason: 'Consistent income history and manageable debt-to-income ratio', contacted: 'Never', consent: true },
  { id: 10084, name: 'Neha Kapoor', initials: 'NK', city: 'Delhi', score: 79, income: 76000, creditScore: 756, balance: 132000, product: 'Standard Personal Loan', code: 'PL_STANDARD', reason: 'Regular salary credits and steady average account balance', contacted: '48 days ago', consent: true },
  { id: 10112, name: 'Vikram Rao', initials: 'VR', city: 'Hyderabad', score: 74, income: 67000, creditScore: 731, balance: 119000, product: 'Standard Personal Loan', code: 'PL_STANDARD', reason: 'Good repayment profile with consistent banking activity', contacted: 'Never', consent: true },
  { id: 10138, name: 'Ananya Iyer', initials: 'AI', city: 'Chennai', score: 72, income: 59000, creditScore: 724, balance: 92000, product: 'Standard Personal Loan', code: 'PL_STANDARD', reason: 'Reliable account activity and low existing obligations', contacted: '37 days ago', consent: true },
];
export const inr = number => new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR', maximumFractionDigits:0}).format(number);
export function draftFor(c) {
  return `Hi ${c.name.split(' ')[0]}, thank you for banking with us! Based on your existing relationship with our bank, you may be interested in learning about our ${c.product.toLowerCase()} options. I'd be happy to walk you through current features and eligibility. Would you like a quick conversation this week? — Your Relationship Manager`;
}
const tools = [
  { name:'get_customer_features', detail:'Retrieve customer profile & account activity', status:'complete' },
  { name:'score_loan_prospects', detail:'Apply eligibility & heuristic scoring', status:'complete' },
  { name:'match_banking_products', detail:'Select appropriate loan category', status:'complete' },
  { name:'check_outreach_permissions', detail:'Verify opt-in & contact frequency', status:'complete' }
];
export function demoReply(prompt, history = []) {
  const p = prompt.toLowerCase();
  const wantsMessage = /whatsapp|message|outreach|draft|write|generate|follow.?up/.test(p);
  const wantsPremium = /premium|high.value|high income|top tier/.test(p);
  const wantsExcluded = /exclude|ineligible|not eligible|why not/.test(p);
  const wantsContext = /previous|those|them|their|shortlist|above/.test(p);
  const lastProspects = [...history].reverse().find(m => m.role === 'assistant' && m.result?.customers)?.result?.customers;
  let selected = wantsContext && lastProspects ? lastProspects : customers;
  if (wantsPremium) selected = selected.filter(c=>c.code==='PL_PREMIUM');
  const foundLimit = p.match(/(?:top|first|show|find|for)\s+(\d{1,2})/);
  selected = selected.slice(0, foundLimit ? Math.max(1,Math.min(20,Number(foundLimit[1]))) : (wantsMessage ? 3 : 5));
  if (wantsExcluded) return { text: 'In a live run, exclusion reasons are calculated from the customer features: unverified KYC, high risk band, credit score below 680, insufficient salary history, EMI-to-income above 40%, active personal loan, pending application, recent decline, or missing outreach consent. Demo fixtures only show eligible prospects; connect the backend for actual excluded records.', tools: tools.slice(0,2), result: null };
  const result = { type:'prospects', customers:selected, messages:wantsMessage ? selected.map(c=>({customerId:c.id, customerName:c.name, content:draftFor(c)})) : [], total:selected.length, mode:'demo' };
  return { text: wantsMessage ? `I've shortlisted ${selected.length} illustrative prospects and prepared personalized WhatsApp drafts. These are drafts for RM review — no messages have been sent.` : `I found ${selected.length} illustrative ${wantsPremium?'premium ':''}personal loan prospects ranked by a heuristic score. Review the customer details and reasons below.`, tools: wantsMessage ? [...tools,{name:'generate_whatsapp_drafts',detail:'Create customer-specific messages',status:'complete'}] : tools, result };
}
