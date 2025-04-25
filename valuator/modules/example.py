from utils.basic_utils import *
from utils.llm_utils import *
from utils.llm_zoo import *
from utils.test_runner import append_to_methods


@append_to_methods
def analyze_as_finance(data: dict):
    corp = data['corp']
    result = gpt_41_nano.invoke(f'make me a report of {corp} in aspect of finance').content
    return {'report': result}


@append_to_methods
def analyze_as_ceo(data: dict):
    corp = data['corp']
    ceo_report = pplx.invoke(f"""
Subject: Request for CEO & Leadership Team Analysis Report for {corp}

Objective: To conduct a comprehensive qualitative analysis of the CEO and key leadership team of [Insert Company Name], focusing on aspects crucial for long-term investment success, as emphasized by renowned investors like Warren Buffett, Charlie Munger, Philip Fisher, Peter Lynch, and considering perspectives from activist investors.

Scope of Analysis: Please structure the report based on the following key areas, addressing the associated questions with evidence and reasoned judgment:

Integrity, Ethics, and Transparency:

Assess the perceived integrity and ethical standards of the leadership.
Evaluate the transparency and candor of communication with shareholders and stakeholders (e.g., admitting mistakes).
Examine the alignment between stated values/promises and actual actions.
Analyze the leadership's reputation within the industry and broader community (incorporating "scuttlebutt" insights if possible).
Competence and Vision:

Evaluate the leadership's depth of understanding of the business and its industry dynamics.
Assess the clarity, coherence, and long-term orientation of the company's strategic vision under the current leadership.
Analyze the leadership's track record and capability in executing strategy effectively.
Examine the company's ability to innovate and adapt to market changes under this leadership (mention R&D focus if relevant).
Assess demonstrated crisis management capabilities.
Capital Allocation Skill:

Analyze the rationality and effectiveness of leadership's capital allocation decisions (reinvestment, dividends, buybacks, M&A).
Evaluate the prudence of past M&A activity and its impact on shareholder value.
Assess the approach to debt management.
Shareholder Friendliness:

Determine if leadership prioritizes long-term shareholder value creation.
Assess if management operates with an "owner's mindset" (e.g., cost control).
Evaluate the appropriateness and structure of executive compensation, checking alignment with long-term performance.
Leadership and Organizational Culture:

Assess the ability to attract, retain, and develop key talent (management depth).
Evaluate the health and productivity of the organizational culture fostered by the leadership (including employee relations).
Examine the effectiveness of delegation and potential for bureaucracy.
Alignment of Interests:

Analyze the extent to which management's interests are aligned with shareholders (e.g., significant insider ownership, "skin in the game").
Assess if leadership ties its personal reputation to the company's success.
Track Record and Experience:

Review the past performance and relevant experience of the CEO and key executives.
Evaluate the consistency in delivering on stated goals and promises.
Information Sources: Utilize publicly available information, including annual reports, investor presentations, earnings call transcripts, reputable news articles, executive interviews, and, where possible, insights gathered from industry sources or checks (scuttlebutt).

Output: Please provide a structured report in English, summarizing findings for each section with supporting evidence and concluding with an overall assessment of the leadership's quality from a long-term investor's perspective. Highlight both strengths and potential risks/concerns.
        """).content
    culture_report = pplx.invoke(f"""
Role: You are an expert organizational analyst specializing in evaluating corporate culture and leadership effectiveness for long-term investment decisions. Your analysis should identify how culture and leadership behaviors impact innovation, talent retention, risk management, and ultimately, sustainable value creation at {corp}.

Objective: Generate a comprehensive, evidence-based qualitative analysis report on the organizational culture and the broader leadership team's influence (beyond just the CEO) at {corp}. Focus on factors critical to operational excellence, adaptability, and long-term investment success.

Input Company: {corp}

Core Task: Analyze {corp}'s organizational culture and leadership influence based on the structure and questions outlined below. For each point, provide specific examples, supporting evidence from cited sources (including qualitative data where available and credible), and clearly articulated reasoning connecting your assessment to potential impacts on the company's performance and long-term prospects.

Key Analysis Areas & Guiding Questions:

Organizational Culture & Talent Dynamics:

Assess: Evaluate the prevailing organizational culture. Is it collaborative, competitive, innovative, bureaucratic, risk-averse, etc.? Provide evidence (e.g., employee reviews, internal communications tone, reported initiatives).
Evaluate: Analyze the company's ability to attract, develop, motivate, and retain high-quality talent across various levels. Are there indicators of high/low morale or turnover? (Consider Glassdoor, LinkedIn insights, news reports).
Examine: Investigate the extent to which the stated company values are reflected in everyday practices, decision-making, and employee behavior. Is there an "espoused vs. enacted" culture gap?
Analyze: Assess the environment for innovation, psychological safety, and constructive dissent. Are employees empowered to experiment and voice concerns?
Determine: Is the culture aligned with the company's stated strategy? Does it support or hinder strategic execution?
Leadership Communication & Influence:

Evaluate: Analyze the clarity, consistency, transparency, and effectiveness of communication from the broader leadership team (beyond the CEO) to employees.
Assess: How well are the company's vision, strategy, and values cascaded and understood throughout the organization?
Examine: Does leadership foster an environment of open dialogue and feedback (both upward and downward)?
Analyze: Assess the perceived authenticity and trustworthiness of the leadership team among employees and external stakeholders.
Governance Interaction & Ethical Tone:

Evaluate: Analyze the quality of interaction and information flow between senior management (below CEO) and the Board of Directors.
Assess: Does the leadership team actively promote and uphold high ethical standards throughout the organization? Are there mechanisms for reporting and addressing ethical concerns?
Examine: How does the leadership team respond to governance recommendations or shareholder concerns conveyed through the board?
Determine: Does the overall "tone at the top" (set by CEO and extended leadership) foster a culture of compliance, integrity, and accountability?
Adaptability, Decision Quality & Execution:

Evaluate: Assess the organization's overall capacity to adapt to market changes, technological disruptions, and competitive pressures, as influenced by leadership effectiveness beyond the CEO.
Analyze: Examine the quality and speed of decision-making processes at various management levels. Is there evidence of effective delegation or bottlenecks?
Assess: Evaluate the effectiveness of cross-functional collaboration and execution on key strategic initiatives. Does the culture support or impede this?
Examine: How does the leadership team learn from past mistakes or operational failures? Is there a culture of continuous improvement?
Information Sources: Utilize publicly available, credible information. Sources may include:

Annual Reports & Sustainability/ESG Reports (sections on culture, employees, values)
Investor Presentations (sections on strategy execution, talent)
Reputable Employee Review Sites (e.g., Glassdoor – use cautiously, look for patterns)
Reputable Financial News Articles, Industry Publications, Case Studies
Company Website (Careers section, 'About Us', Mission/Values statements)
Executive Interviews, Conference Talks (where leadership discusses culture/operations)
Governance Reports & Proxy Statements (indirect indicators via board reports, proposals)
Output Requirements:

Format: A structured, professional report written in English.
Content: Address each section above comprehensively. Provide clear assessments supported by specific evidence (qualitative and quantitative where possible) and logical reasoning. Explicitly cite sources.
Synthesis: Conclude with an overall executive summary assessing the health and effectiveness of {corp}'s organizational culture and the quality of its broader leadership influence. Clearly highlight cultural strengths that support investment theses, and identify cultural/leadership risks or weaknesses that could impede future success.
Tone: Maintain an objective, analytical, and evidence-based tone.
        """).content
    result = gpt_41_mini.invoke(f"""
Role: You are a Senior Investment Analyst or Portfolio Manager tasked with critically reviewing preliminary research reports and synthesizing them into a final, high-conviction investment assessment document. Your expertise lies in identifying inconsistencies, evaluating the strength of evidence, and integrating diverse qualitative analyses into a cohesive and actionable conclusion.

Objective: Critically review the two provided input reports ("ceo_report" and "culture_report") for consistency, evidence quality, analytical rigor, and logical coherence. Subsequently, synthesize the validated findings into a single, consolidated Final Leadership & Organizational Quality Report for {corp}, suitable for informing a long-term investment decision.

Input Reports:

"ceo_report" CEO Analysis Report for {corp} :
{ceo_report}
"culture_report" Organizational Culture & Leadership Influence Analysis Report for {corp} :
{culture_report}
Input Company: {corp} (Ensure consistency across both reports)

Core Task:

Critical Review & Validation:

Consistency Check: Compare findings across "ceo_report" and "culture_report". Are there contradictions or significant discrepancies regarding strategic direction, leadership style, cultural attributes, or execution capabilities? Identify and flag any inconsistencies.
Evidence Verification: Assess whether the conclusions drawn in each report are adequately supported by the specific evidence cited within them. Is the evidence relevant, credible, and sufficient?
Analytical Rigor: Evaluate the depth and objectivity of the analysis in both reports. Is the reasoning sound? Are potential biases acknowledged or mitigated?
Cross-Reference Key Themes (incorporating image insights):
Strategic Direction Validity: Does the CEO's stated strategy "ceo_report" align with the organizational capacity and cultural realities described in "culture_report"? Is the strategic direction assessment in "ceo_report" supported by evidence of market understanding and adaptability mentioned in "culture_report"?
Execution Assessment: Are claims of execution capability in "ceo_report" consistent with the analysis of organizational culture, talent dynamics, and decision-making processes in "culture_report"?
Shareholder Alignment Check: Does the assessment of shareholder friendliness (compensation, capital allocation in "ceo_report") align with the broader governance context and ethical tone described in "culture_report"?
Cultural Assessment Validity: Is the cultural analysis in "culture_report" nuanced and supported by diverse evidence points? Does it connect logically to leadership behaviors described in "ceo_report"?
Risk Factor Confirmation: Are the key risks identified in both reports consistent? Are there risks highlighted in one report that are inadequately addressed or contradicted in the other?
Synthesis & Integration:

Combine Findings: Integrate the validated key findings, insights, strengths, and weaknesses from both "ceo_report" and "culture_report" into a unified narrative. Avoid simple repetition; synthesize the information logically (e.g., group by themes like Strategy & Vision, Execution Capability, Culture & Talent, Governance & Integrity, Risk Factors).
Refine Narrative: Ensure the combined analysis flows logically and presents a clear, coherent picture of the company's overall leadership and organizational quality. Eliminate redundancy.
Final Assessment & Conclusion:

Overall Judgement: Based on the synthesized analysis, provide a final, nuanced overall assessment of the leadership team's quality and the organization's health from a long-term investor's perspective.
Summarize Key Factors: Clearly articulate the most critical leadership strengths supporting a potential investment and the most significant weaknesses or risks acting as potential deterrents.
Confidence Level (Optional): Briefly comment on the overall confidence level in the assessment based on the quality and consistency of the input reports.
Output Requirements:

Format: A single, polished, and professional Final Leadership & Organizational Quality Report written in English.
Structure: Recommend including:
Executive Summary (Overall assessment, key strengths/risks)
Integrated Analysis (Synthesized findings structured by key themes)
Key Risks & Mitigating Factors Summary
Conclusion (Final investment implications regarding leadership/culture)
Content: The report must be based only on the validated information from "ceo_report" and "culture_report". Clearly articulate the synthesis process and the rationale behind the final assessment. Highlight areas where input reports were inconsistent or lacked strong evidence, if applicable.
Tone: Maintain a concise, objective, critical, and decisive tone suitable for a final investment recommendation document.
        """).content
    return {'ceo_report': result}


@append_to_methods
def analyze_as_business(data: dict):
    corp = data['corp']
    result = gpt_41_nano.invoke(f'make me a report of {corp} in aspect of business act brilliance').content
    return {'report': result}


@append_to_methods
def summary(data: dict):
    finance_report = analyze_as_finance(data)['report']
    ceo_report = analyze_as_ceo(data)['ceo_report']
    business_report = analyze_as_business(data)['report']
    result = gpt_41_mini.invoke(
        f'summarize these three contents: 1 - {finance_report} \n\n 2 - {ceo_report} \n\n 3 - {business_report}').content
    return {'summary': result}