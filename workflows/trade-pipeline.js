export const meta = {
  name: 'trade-pipeline',
  description: 'TradingClawd: analysts, bull/bear debate, research manager, trader, risk debate and portfolio manager for each ticker',
  whenToUse: 'Started by the /tradingclawd:trade skills with the JSON that scripts/prepare_run.py prints; not for direct use.',
  phases: [
    { title: 'Analysts', detail: 'market, social, news and fundamentals analysts in parallel' },
    { title: 'Research debate', detail: 'bull and bear take turns' },
    { title: 'Research manager', detail: 'investment plan (schema-checked)' },
    { title: 'Trader', detail: 'transaction proposal (schema-checked)' },
    { title: 'Risk debate', detail: 'aggressive, conservative and neutral take turns' },
    { title: 'Portfolio manager', detail: 'final decision (schema-checked)' },
  ],
}

// ---------------------------------------------------------------------------
// Inputs (the object scripts/prepare_run.py prints)
// ---------------------------------------------------------------------------

const input = typeof args === 'string' ? JSON.parse(args) : args || {}
const required = ['plugin_dir', 'data_dir', 'trade_date', 'tickers', 'debate_rounds', 'risk_rounds', 'start_at', 'stop_after']
const missingArgs = required.filter((k) => input[k] === undefined)
if (missingArgs.length) {
  throw new Error(`trade-pipeline needs the JSON from scripts/prepare_run.py; missing ${missingArgs.join(', ')}`)
}
const { plugin_dir, data_dir, trade_date, tickers, debate_rounds, risk_rounds } = input
const STAGES = ['analyze', 'debate', 'decide']
const runs = (stage) =>
  STAGES.indexOf(stage) >= STAGES.indexOf(input.start_at) && STAGES.indexOf(stage) <= STAGES.indexOf(input.stop_after)
const PLAN_ONLY = input.plan_only === true

// ---------------------------------------------------------------------------
// Output schemas for the three decision agents
// ---------------------------------------------------------------------------

const FIVE_TIER = ['Buy', 'Overweight', 'Hold', 'Underweight', 'Sell']
const RESEARCH_PLAN = {
  type: 'object',
  properties: {
    recommendation: {
      type: 'string', enum: FIVE_TIER,
      description: 'Exactly one of Buy / Overweight / Hold / Underweight / Sell. Conflicting arguments alone are not a ' +
        'reason to Hold: commit to the stronger side, sized by how decisively it wins. Choose Hold only when the ' +
        'evidence is still balanced after weighing, or too thin to support a call.',
    },
    rationale: {
      type: 'string',
      description: 'Conversational summary of the key points from both sides of the debate, ending with which ' +
        'arguments led to the recommendation.',
    },
    strategic_actions: {
      type: 'string',
      description: 'Concrete steps for the trader to implement the recommendation, including sizing guidance ' +
        'relative to a standard allocation.',
    },
  },
  required: ['recommendation', 'rationale', 'strategic_actions'],
}
const TRADER_PROPOSAL = {
  type: 'object',
  properties: {
    action: { type: 'string', enum: ['Buy', 'Hold', 'Sell'], description: 'The transaction direction.' },
    reasoning: {
      type: 'string',
      description: 'The case for this action, anchored in the analysts\' reports and the research plan. Two to four sentences.',
    },
    entry_price: {
      type: ['number', 'null'],
      description: 'Entry price as an absolute number in the quote currency (e.g. 189.5), never a percentage or a ' +
        'range; null if you cannot state one.',
    },
    stop_loss: {
      type: ['number', 'null'],
      description: 'Stop-loss as an absolute price in the quote currency; convert a percentage distance to the price ' +
        'it implies, or null.',
    },
    position_sizing: {
      type: ['string', 'null'],
      description: 'Sizing guidance in one or two sentences, e.g. "5% of portfolio"; null if none.',
    },
  },
  required: ['action', 'reasoning', 'entry_price', 'stop_loss', 'position_sizing'],
}
const PORTFOLIO_DECISION = {
  type: 'object',
  properties: {
    rating: {
      type: 'string', enum: FIVE_TIER,
      description: 'Exactly one of Buy / Overweight / Hold / Underweight / Sell. Conflicting arguments alone are not a ' +
        'reason to Hold: commit to the stronger side, sized by how decisively it wins. Choose Hold only when the ' +
        'evidence is still balanced after weighing, or too thin to support a call.',
    },
    executive_summary: {
      type: 'string',
      description: 'A concise action plan covering entry strategy, position sizing, key risk levels and time horizon. ' +
        'Two to four sentences; the detail belongs in investment_thesis.',
    },
    investment_thesis: {
      type: 'string',
      description: 'Detailed reasoning anchored in specific evidence from the analysts\' debate, incorporating lessons ' +
        'from prior decisions in the memory log when there are any.',
    },
    price_target: { type: ['number', 'null'], description: 'Target price in the quote currency, or null.' },
    time_horizon: { type: ['string', 'null'], description: 'Recommended holding period, e.g. "3-6 months", or null.' },
  },
  required: ['rating', 'executive_summary', 'investment_thesis', 'price_target', 'time_horizon'],
}

// ---------------------------------------------------------------------------
// Agent calls (plan_only lists them instead of running them)
// ---------------------------------------------------------------------------

const planned = []
async function call(prompt, opts) {
  if (!PLAN_ONLY) return agent(prompt, opts)
  planned.push(`${opts.phase} | ${opts.label} | ${opts.agentType}${opts.schema ? ' | schema' : ''}`)
  if (!opts.schema) return `${opts.label} done`
  const stub = {}
  for (const [k, v] of Object.entries(opts.schema.properties)) stub[k] = v.enum ? v.enum[0] : null
  return stub
}

const ANALYSTS = ['market', 'social', 'news', 'fundamentals']
const REPORT_FILE = { market: 'market_report.md', social: 'sentiment_report.md', news: 'news_report.md', fundamentals: 'fundamentals_report.md' }

function context(t) {
  return `ticker: ${t.ticker}\ntrade_date: ${trade_date}\nresults_dir: ${t.results_dir}\nplugin_dir: ${plugin_dir}`
}

function missingNote(missing) {
  if (!missing.length) return ''
  return `\n\nThese analyst reports were not produced in this run: ${missing.join(', ')}. ` +
    'Treat that data as unavailable, not as an empty finding.'
}

function turnsNote(dir, turns) {
  if (!turns.length) return 'Prior turns: none. You speak first in this debate, so open with your own case.'
  return `Prior turns, oldest first (read every one before writing): ${turns.map((f) => `${dir}/${f}`).join(', ')}`
}

// ---------------------------------------------------------------------------
// One ticker's chain. Tickers run side by side; none waits for another.
// ---------------------------------------------------------------------------

async function runTicker(t) {
  const T = t.ticker
  const result = { ticker: T, results_dir: t.results_dir, status: 'running', stage_reached: null, missing_reports: [] }
  const stop = (stage, reason) => {
    result.status = 'REVIEW'
    result.failure = `${stage}: ${reason}`
    log(`${T}: stopped at ${stage} (${reason}); the ticker needs review`)
    return result
  }

  if (runs('analyze')) {
    const replies = await parallel(ANALYSTS.map((a) => () =>
      call(context(t), { label: `${a}:${T}`, phase: 'Analysts', agentType: `tradingclawd:ta-${a}-analyst` })))
    result.missing_reports = ANALYSTS.filter((a, i) => !replies[i]).map((a) => REPORT_FILE[a])
    if (result.missing_reports.length === ANALYSTS.length) return stop('analyze', 'no analyst produced a report')
    result.stage_reached = 'analyze'
    log(`${T}: analysts done${result.missing_reports.length ? `; missing ${result.missing_reports.join(', ')}` : ''}`)
  }

  if (runs('debate')) {
    const turns = []
    for (let round = 1; round <= debate_rounds; round++) {
      for (const side of ['bull', 'bear']) {
        const file = `${side}_${round}.md`
        const reply = await call(
          `${context(t)}\nround: ${round}\nwrite_to: ${t.results_dir}/debate_turns/${file}\n` +
            turnsNote(`${t.results_dir}/debate_turns`, turns) + missingNote(result.missing_reports),
          { label: `${side}${round}:${T}`, phase: 'Research debate', agentType: `tradingclawd:ta-${side}-researcher` })
        if (!reply) return stop('debate', `${side} researcher returned nothing in round ${round}`)
        turns.push(file)
      }
    }
    const plan = await call(
      `${context(t)}\nDebate turns, oldest first: ${turns.map((f) => `${t.results_dir}/debate_turns/${f}`).join(', ')}\n` +
        `Write the plan to ${t.results_dir}/research_plan.json, then return exactly the same object.` +
        missingNote(result.missing_reports),
      { label: `research-manager:${T}`, phase: 'Research manager', agentType: 'tradingclawd:ta-research-manager',
        schema: RESEARCH_PLAN, effort: 'high' })
    if (!plan) return stop('debate', 'research manager returned no valid plan')
    result.research_recommendation = plan.recommendation
    result.stage_reached = 'debate'
    log(`${T}: research manager recommends ${plan.recommendation}`)
  }

  if (runs('decide')) {
    const proposal = await call(
      `${context(t)}\nWrite the proposal to ${t.results_dir}/trader_proposal.json, then return exactly the same object.` +
        missingNote(result.missing_reports),
      { label: `trader:${T}`, phase: 'Trader', agentType: 'tradingclawd:ta-trader', schema: TRADER_PROPOSAL })
    if (!proposal) return stop('decide', 'trader returned no valid proposal')
    result.trader_action = proposal.action

    const turns = []
    for (let round = 1; round <= risk_rounds; round++) {
      for (const side of ['aggressive', 'conservative', 'neutral']) {
        const file = `${side}_${round}.md`
        const reply = await call(
          `${context(t)}\nround: ${round}\nwrite_to: ${t.results_dir}/risk_turns/${file}\n` +
            turnsNote(`${t.results_dir}/risk_turns`, turns) + missingNote(result.missing_reports),
          { label: `${side}${round}:${T}`, phase: 'Risk debate', agentType: `tradingclawd:ta-risk-${side}` })
        if (!reply) return stop('decide', `${side} risk analyst returned nothing in round ${round}`)
        turns.push(file)
      }
    }

    const decision = await call(
      `${context(t)}\ndata_dir: ${data_dir}\n` +
        `Risk debate turns, oldest first: ${turns.map((f) => `${t.results_dir}/risk_turns/${f}`).join(', ')}\n` +
        `Write the decision to ${t.results_dir}/portfolio_decision.json, then return exactly the same object.` +
        missingNote(result.missing_reports),
      { label: `portfolio-manager:${T}`, phase: 'Portfolio manager', agentType: 'tradingclawd:ta-portfolio-manager',
        schema: PORTFOLIO_DECISION, effort: 'high' })
    if (!decision) return stop('decide', 'portfolio manager returned no valid decision')
    Object.assign(result, {
      rating: decision.rating,
      executive_summary: decision.executive_summary,
      price_target: decision.price_target,
      time_horizon: decision.time_horizon,
    })
    result.stage_reached = 'decide'
    log(`${T}: final rating ${decision.rating}`)
  }

  result.status = 'done'
  return result
}

const outcomes = await parallel(tickers.map((t) => () => runTicker(t)))
const results = outcomes.map((r, i) => r || { ticker: tickers[i].ticker, results_dir: tickers[i].results_dir, status: 'REVIEW', failure: 'the ticker chain crashed' })

return {
  trade_date,
  data_dir,
  memory_log: input.memory_log,
  start_at: input.start_at,
  stop_after: input.stop_after,
  results,
  ...(PLAN_ONLY ? { planned } : {}),
}
