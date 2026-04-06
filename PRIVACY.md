# ShuttleScope Privacy Notice
## Version 1.0 — Effective upon first use of the Software by any Contributing Party

---

### PRELIMINARY STATEMENT

This Privacy Notice ("Notice") is issued by the Licensor of ShuttleScope as
identified in the Software License ("Licensor," "we," "us," or "our") and
describes in detail the categories, purposes, legal bases, retention practices,
security measures, cross-border transfer mechanisms, and data subject rights
applicable to the collection, use, storage, and disclosure of personal
information — including, without limitation, information relating to identified
and identifiable professional and amateur athletes — in connection with the
ShuttleScope software application ("Software"), any associated application
programming interfaces, data synchronization services, analytics infrastructure,
and machine learning systems operated by the Licensor (collectively, the
"Service").

This Notice is addressed to: (a) natural persons who use the Software as analysts,
coaches, or administrators ("Users"); (b) natural persons whose performance data
is recorded, annotated, or analyzed through the Software, whether or not such
persons are themselves Users ("Athletes" or "Data Subjects"); and (c) legal
entities that deploy the Software on behalf of teams, federations, or other
organizations ("Organizations"), whose own obligations are further described in
`DATA_CONTRIBUTION_TERMS.md`.

THIS NOTICE SHOULD BE READ IN CONJUNCTION WITH `DATA_CONTRIBUTION_TERMS.md`,
WHICH GOVERNS THE INTELLECTUAL PROPERTY AND DATA LICENSING DIMENSIONS OF DATA
SUBMITTED THROUGH THE SOFTWARE. THIS NOTICE ADDRESSES THE PERSONAL DATA AND
PRIVACY DIMENSIONS OF THAT SAME DATA.

---

### ARTICLE I — SCOPE AND APPLICABILITY

**1.1 Material Scope.**  
This Notice applies to the processing of personal data — meaning any information
relating to an identified or identifiable natural person ("personal data" or
"personal information") — by the Licensor acting in the capacity of either data
controller or data processor, as applicable in light of the deployment context
described in Article III. This Notice applies regardless of whether the Software
is deployed in a fully local offline mode, a hybrid mode involving periodic data
export, or any Network-Connected Mode (as defined in `DATA_CONTRIBUTION_TERMS.md`)
involving real-time or batch transmission to the Licensor's infrastructure.

**1.2 Territorial Scope.**  
This Notice is intended to address the privacy expectations and legal obligations
relevant to the Licensor's operations globally. Specific provisions address:

  **(a)** requirements arising under Japanese law, including the Act on the
  Protection of Personal Information (Act No. 57 of 2003, as amended, "APPI") and
  supplementary guidelines issued by the Personal Information Protection Commission
  of Japan ("PPC"), which constitute the Licensor's primary regulatory framework
  as of the effective date of this Notice;

  **(b)** requirements arising under Regulation (EU) 2016/679 of the European
  Parliament and of the Council (the "General Data Protection Regulation" or
  "GDPR") and implementing legislation in EU and EEA member states, to the extent
  that the Software processes data of individuals located in the EEA or that EU/EEA
  law is otherwise applicable;

  **(c)** requirements arising under the UK GDPR as incorporated into UK law by
  the Data Protection Act 2018, to the extent applicable;

  **(d)** requirements arising under the Personal Information Protection and
  Electronic Documents Act (Canada, "PIPEDA") and successor legislation, to the
  extent applicable; and

  **(e)** requirements arising under any other national, state, or sectoral data
  protection legislation applicable to specific deployments of the Software,
  including without limitation legislation in South Korea (the Personal Information
  Protection Act, "PIPA"), Brazil (the Lei Geral de Proteção de Dados, "LGPD"),
  Australia (the Privacy Act 1988), and the United States (sector-specific and
  state-level legislation).

Organizations deploying the Software in regulated jurisdictions remain
independently responsible for their own compliance with applicable law.

**1.3 Exclusions.**  
This Notice does not govern the processing of personal data by Organizations
acting in their capacity as data controllers with respect to their own employees,
athletes, or members. Each Organization remains responsible for its own privacy
notices, consent mechanisms, and legal bases for the processing it conducts
within its own deployment of the Software.

---

### ARTICLE II — CATEGORIES OF PERSONAL DATA

**2.1 User Account and Access Data.**  
In connection with user authentication, authorization, and session management, the
Software may process:

  **(a)** username or user identifier;
  **(b)** role designation (analyst, coach, or player role within the application);
  **(c)** player account linkages (where a user account is associated with an
  athlete's own data profile);
  **(d)** session metadata including access timestamps, device type, operating
  system version, and application version;
  **(e)** application configuration preferences; and
  **(f)** audit log entries recording actions taken within the Software.

**2.2 Athlete Performance and Annotation Data.**  
The core operational data processed by the Software consists of structured records
relating to identified or identifiable athletes, including:

  **(a)** athlete full names and, where provided, name romanizations or
  transliterations;
  **(b)** team, club, federation, or national association affiliation;
  **(c)** nationality;
  **(d)** date of birth or birth year;
  **(e)** world ranking position and ranking history, to the extent entered or
  imported;
  **(f)** dominant hand designation (right or left);
  **(g)** designation as a "target" athlete for primary analysis focus;
  **(h)** match history including opponents, venues, dates, tournament names,
  tournament tier designations, round designations, and match formats;
  **(i)** match results (win, loss, walkover, or unfinished) from the perspective
  of each identified athlete;
  **(j)** stroke-level annotation records as described in Section 1.4 of
  `DATA_CONTRIBUTION_TERMS.md`, comprising among other fields: shot type
  classifications, court zone impact and landing designations, body-position
  coordinates, above-net indicators, and other tactical parameters; and
  **(k)** free-text notes entered by analysts or coaches in relation to specific
  matches or athletes.

**2.3 Derived Performance Profiles.**  
The analytical functions of the Software generate derived data items that, when
associated with identified athletes, constitute personal data relating to those
athletes. These include:

  **(a)** computed win rates disaggregated by shot type, tournament level, match
  result, rally length, score phase, and other dimensions;
  **(b)** shot pattern profiles including transition probability matrices that
  describe individual tactical tendencies;
  **(c)** expected possession value (EPV) estimates and shot influence scores
  associated with individual stroke sequences attributable to identified athletes;
  **(d)** player type classifications derived from rally-length win rate patterns;
  **(e)** pressure-situation performance indicators (deuce win rates, endgame win
  rates relative to normal-play win rates);
  **(f)** post-long-rally fatigue or momentum indicators;
  **(g)** first-return zone preference profiles; and
  **(h)** any other analytical output that is stored in association with an
  identified athlete's profile within the Software's data schema.

The data items described in this Section 2.3 may, individually or in combination,
reveal information about an athlete's physical condition, tactical vulnerabilities,
strategic tendencies, or competitive performance levels. Such data may be
commercially sensitive and may be subject to elevated protection requirements
under applicable law.

**2.4 Operational and Telemetry Data.**  
The Software generates operational records that may include personal data:

  **(a)** error logs and crash reports that may incidentally record user
  identifiers or active data state at the time of an error;
  **(b)** performance metrics and timing records generated during annotation
  sessions; and
  **(c)** usage event records capturing the sequence and frequency of feature
  use within a session.

**2.5 Data Not Collected.**  
As of the effective date of this Notice, and subject to future updates:

  **(a)** the Software does not collect health, medical, or injury data about
  athletes unless such data is voluntarily entered by an analyst or coach in a
  free-text notes field;
  **(b)** the Software does not collect financial information about athletes or
  Organizations;
  **(c)** the Software does not collect continuous biometric data (e.g., heart
  rate, GPS tracks) unless such data is generated from video analysis functions
  and associated with performance records;
  **(d)** the Software does not, in offline mode, transmit any personal data to
  the Licensor's servers; and
  **(e)** the Software's video processing, where applicable, operates on
  locally stored files; video content is not transmitted to the Licensor's
  infrastructure under these Terms.

---

### ARTICLE III — PROCESSING ROLES AND RESPONSIBILITIES

**3.1 Local Offline Deployment.**  
Where the Software is operated exclusively in offline mode on hardware under the
Organization's exclusive control, with no data synchronization, no cloud backup,
and no API calls to Licensor infrastructure:

  **(a)** the Organization acts as the sole data controller or equivalent for all
  personal data processed within the Software;
  **(b)** the Licensor does not receive, access, or process personal data as a
  consequence of such deployment; and
  **(c)** the obligations of the Licensor under this Notice apply, if at all, only
  if the Organization subsequently transmits data to the Licensor through a
  different channel (such as a support request containing exported data, a bug
  report containing error logs, or use of any Network-Connected Mode feature).

**3.2 Network-Connected Mode Deployment.**  
Where the Software is operated in a mode that results in the transmission of
personal data to the Licensor's infrastructure:

  **(a)** the Licensor acts as a data processor with respect to the Organization's
  instructions for service delivery purposes; and
  **(b)** the Licensor acts as an independent data controller with respect to its
  own use of that data for analytical, research, and model development purposes
  as described in `DATA_CONTRIBUTION_TERMS.md`, subject to the lawful basis
  provisions of Article IV.

**3.3 Athlete Access via Player Role.**  
Where the Software is configured to permit an athlete to access the Software in
the "player" role:

  **(a)** the athlete accesses a restricted view of their own performance data
  subject to role-based access controls;
  **(b)** coach-only and analyst-only content (including direct weakness
  characterizations, EPV scores, and raw comparative analytics) is suppressed from
  the player-facing view in accordance with the Software's design;
  **(c)** the Licensor's processing of data in connection with such access is
  subject to this Notice in its entirety; and
  **(d)** the Organization remains responsible for determining whether the
  athlete's use of the player-role interface requires a separate consent mechanism,
  data sharing notice, or agreement under applicable law.

---

### ARTICLE IV — PURPOSES AND LEGAL BASES FOR PROCESSING

**4.1 Purposes.**  
The Licensor may process personal data for the following purposes, each of which
is described with particularity below:

  **(a) Service Delivery:** Processing necessary to operate the Software's
  annotation, analysis, reporting, and visualization functions in response to
  user interactions, including the generation of performance reports, analytical
  dashboards, and coaching summaries.

  **(b) Software Maintenance and Improvement:** Processing necessary for
  debugging, testing, performance optimization, security hardening, feature
  development, and quality assurance of the Software, including the use of
  anonymized or pseudonymized data in test environments.

  **(c) Model Training and Algorithm Development:** Processing of Contributed Data
  — including personal data relating to athletes to the extent authorized by the
  Data Grant in `DATA_CONTRIBUTION_TERMS.md` — for the purpose of training,
  validating, benchmarking, and improving machine learning models, statistical
  models, and analytical algorithms, whether or not such models are deployed
  within the Software.

  **(d) Research:** Processing of personal data — including athlete performance
  profiles — for sports science research, tactical analysis research, and related
  academic or applied research, subject to appropriate anonymization or
  pseudonymization where feasible and where not inconsistent with the research
  purpose.

  **(e) Security and Fraud Prevention:** Processing of operational logs,
  access records, and session data for the purpose of detecting, investigating,
  and preventing unauthorized access, data breaches, abuse, and security
  incidents.

  **(f) Legal Compliance:** Processing required to comply with applicable laws,
  regulations, judicial orders, regulatory investigations, or other legally
  mandated obligations.

  **(g) Data Subject Rights Fulfillment:** Processing required to respond to
  access requests, correction requests, deletion requests, portability requests,
  and other data subject rights as described in Article VIII.

**4.2 Legal Bases.**  

  **(a) APPI (Japan):** The Licensor's processing activities under this Notice
  are conducted on the basis of: (i) the necessity of processing for the
  performance of a contract with the Organization (Article 18 of APPI with respect
  to service delivery); (ii) the legitimate interests of the Licensor in
  developing, improving, and commercializing sports analytics technology, provided
  such interests do not override the fundamental rights and interests of the Data
  Subjects; and (iii) consent, where required by the APPI or supplementary PPC
  guidelines, including for the provision of personal data to third parties or
  for uses not initially anticipated.

  **(b) GDPR (EU/EEA):** Where GDPR applies, the Licensor relies on: (i) Article
  6(1)(b) (contract performance) for service delivery; (ii) Article 6(1)(f)
  (legitimate interests) for product improvement, security, and research purposes,
  subject to a balancing test conducted in favor of the Licensor's commercial and
  research interests balanced against the Data Subjects' reasonable expectations
  as athletes in a competitive sport context; and (iii) Article 6(1)(a) (consent)
  where required. Where the data constitutes "special categories of personal data"
  under Article 9 GDPR (which may include health or biometric data to the extent
  entered), the legal basis is the explicit consent of the Data Subject (Article
  9(2)(a)) or, where consent cannot practicably be obtained, the substantial
  public interest basis under Article 9(2)(g) as implemented in national law,
  subject to appropriate safeguards.

  **(c) Other Jurisdictions:** The Licensor shall rely on comparable legal bases
  under applicable national legislation. Organizations are responsible for
  verifying that the legal basis asserted by the Licensor is recognized and
  sufficient under the law applicable to their specific deployment.

---

### ARTICLE V — SENSITIVE DATA: ATHLETE PERFORMANCE PROFILES

**5.1 Elevated Risk Acknowledgment.**  
The parties acknowledge that derived performance profiles of individual athletes
— as described in Section 2.3 — carry elevated sensitivity risks distinct from
ordinary personal data, because such profiles:

  **(a)** may reveal tactical vulnerabilities that, if disclosed to opposing teams
  or agents, could adversely affect an athlete's competitive outcomes or
  professional reputation;

  **(b)** may reveal performance trends that, if disclosed to sports organizations
  or agents during contract negotiations, could affect an athlete's economic
  position;

  **(c)** may constitute commercially valuable proprietary intelligence belonging
  to the athlete, the athlete's organization, or both; and

  **(d)** may carry implications regarding an athlete's physical or mental
  condition that could, in some contexts, engage health data protection frameworks.

**5.2 Protective Measures Specific to Athlete Performance Profiles.**  
In recognition of the elevated sensitivity described in Section 5.1, the Licensor
shall:

  **(a)** maintain logical separation between athlete performance profiles
  associated with different Contributing Party deployments, such that data from
  one Organization is not disclosed to a competing Organization in an identifiable
  form;

  **(b)** apply pseudonymization techniques when athlete performance profiles are
  used in aggregated research or model training datasets to the extent technically
  feasible without materially impairing the analytical value of such data;

  **(c)** treat requests by identified athletes for access to, correction of, or
  deletion of their performance profiles as high-priority requests subject to the
  timelines set forth in Article VIII; and

  **(d)** not sell, license, or disclose athlete performance profiles in
  identifiable form to third-party commercial data brokers, competing sports
  analytics platforms, or other parties whose primary business involves
  aggregating and reselling sports performance intelligence about identified
  athletes, without the prior written consent of the Contributing Party.

**5.3 Note on Aggregated Data.**  
The provisions of Section 5.2 apply to data in identifiable form. The Licensor's
use of aggregated, anonymized, or pseudonymized data — where the re-identification
of specific individuals is not reasonably possible — is not restricted by Section
5.2 and is governed solely by the Data Grant in `DATA_CONTRIBUTION_TERMS.md`.

---

### ARTICLE VI — DATA SHARING AND DISCLOSURE

**6.1 General.**  
Personal data is not sold. Personal data may be disclosed to third parties in the
following circumstances only:

  **(a) Service Providers and Subprocessors:** The Licensor may engage cloud
  infrastructure providers, database hosting providers, analytics platforms, model
  training infrastructure operators, and other service providers to process
  personal data on behalf of the Licensor. Such providers are engaged under data
  processing agreements or equivalent contractual instruments requiring data
  protection standards at least as protective as those described in this Notice.

  **(b) Research Collaboration:** The Licensor may share Athlete and Personnel
  Data in pseudonymized or aggregated form with research collaborators, academic
  institutions, or sports science researchers for purposes consistent with the
  Data Grant. Identifiable data shared with research collaborators is subject to
  appropriate data sharing agreements.

  **(c) Legal Process and Regulatory Compliance:** Personal data may be disclosed
  in response to lawfully issued judicial orders, regulatory investigations, law
  enforcement requests, or other legal obligations. The Licensor will, where
  legally permissible and operationally feasible, notify the affected Contributing
  Party before disclosing personal data in response to legal process.

  **(d) Corporate Transactions:** In the event of a merger, acquisition, asset
  sale, business transfer, restructuring, or financing transaction, personal data
  may be transferred to the successor entity, provided that such successor entity
  is bound by this Notice or a successor privacy notice providing materially
  equivalent protections.

  **(e) Safety and Security:** Personal data may be disclosed where reasonably
  necessary to protect the physical safety of any person, prevent fraud, or
  protect the security, integrity, or functionality of the Software or Service.

**6.2 Cross-Border Transfers.**  
Personal data may be transferred to and processed in countries other than the
country of original collection. For transfers subject to GDPR or equivalent
restrictions:

  **(a)** transfers to countries with an applicable adequacy decision are made on
  the basis of such decision;

  **(b)** transfers to countries without an adequacy decision are made on the
  basis of standard contractual clauses as adopted or approved by the relevant
  supervisory authority, supplementary technical and organizational measures
  appropriate to the risk profile of the data, and a transfer impact assessment
  where required; and

  **(c)** contributing Organizations in Japan are advised that, with respect to
  any cross-border provision of personal data to the Licensor where the Licensor
  is located outside Japan, the Organization should confirm that either (i) the
  recipient country has a personal information protection system deemed equivalent
  by the PPC, or (ii) the recipient has implemented equivalent protective measures,
  or (iii) the Data Subject has consented to such transfer after being informed of
  the relevant country's personal information protection system.

---

### ARTICLE VII — RETENTION

**7.1 General Principles.**  
Personal data is retained for no longer than necessary to fulfill the purposes
for which it was collected, or as required by law, contract, or legitimate
operational necessity. Retention periods are determined based on the following
considerations:

  **(a)** the period during which the Software is actively deployed by the
  Contributing Party;
  **(b)** the minimum period required for effective model training, where
  Contributed Data is used for that purpose;
  **(c)** legal obligations requiring retention for minimum statutory periods;
  **(d)** limitation periods applicable to potential claims arising from the data;
  **(e)** business continuity and disaster recovery requirements; and
  **(f)** the data subject deletion or restriction requests described in Article
  VIII, to the extent that such requests override the foregoing retention periods.

**7.2 Post-Termination Retention.**  
Upon termination of the Software License or cessation of a Contributing Party's
use of the Software, personal data associated with that Contributing Party will
be deleted or anonymized within a reasonable period, subject to:

  **(a)** retention required for legal compliance, tax, audit, or regulatory
  purposes;
  **(b)** retention of data already incorporated into trained model weights in a
  manner that does not permit extraction of identifiable individual records; and
  **(c)** retention of operational and audit logs for security and incident
  response purposes for such period as the Licensor reasonably determines to be
  necessary.

---

### ARTICLE VIII — DATA SUBJECT RIGHTS

**8.1 Applicable Rights.**  
Depending on the jurisdiction in which the Data Subject is located and the
applicable legal framework, Data Subjects may have rights including the right to:

  **(a)** access a copy of personal data held by the Licensor relating to the
  Data Subject;
  **(b)** correct inaccurate personal data;
  **(c)** request erasure of personal data, subject to the limitations described
  in Section 8.4;
  **(d)** restrict the processing of personal data pending resolution of a
  dispute about accuracy or lawfulness;
  **(e)** receive personal data in a structured, commonly used, machine-readable
  format (data portability), where technically feasible;
  **(f)** object to processing based on legitimate interests or for direct
  marketing purposes; and
  **(g)** lodge a complaint with the relevant data protection supervisory authority.

**8.2 Routing of Requests.**  
Where the Licensor acts as a data processor on behalf of an Organization:

  **(a)** Data Subject requests should be directed in the first instance to the
  Organization acting as data controller, which is responsible for determining
  the appropriate response;
  **(b)** the Licensor shall provide reasonable assistance to the Organization in
  responding to Data Subject requests, in accordance with applicable data
  processing agreements.

Where the Licensor acts as an independent data controller:

  **(c)** Data Subject requests may be directed to the Licensor through the
  contact mechanism specified in Article X.

**8.3 Response Timelines.**  
The Licensor shall respond to verified Data Subject requests within:

  **(a)** one month of receipt, with the possibility of extension for a further
  two months where the complexity or number of requests so requires, under GDPR;
  **(b)** two weeks of receipt where the applicable legal framework is APPI; and
  **(c)** such other timeline as required by applicable law in other
  jurisdictions.

**8.4 Limitations on Erasure.**  
The right to erasure is subject to the following limitations:

  **(a)** personal data incorporated into trained model weights where individual
  data cannot practicably be extracted or deleted without retraining the model
  from scratch may be addressed through model retraining schedules rather than
  immediate deletion, provided that the Licensor takes reasonable steps to
  minimize the ongoing influence of such data on model outputs;

  **(b)** personal data required to be retained for legal, audit, tax, or
  regulatory compliance purposes shall be retained for the minimum required period
  notwithstanding an erasure request; and

  **(c)** erasure of athlete performance data held within an Organization's own
  deployment is the responsibility of the Organization and must be addressed
  through the Organization's own data management procedures.

---

### ARTICLE IX — SECURITY

**9.1 Technical and Organizational Measures.**  
The Licensor implements and maintains technical and organizational security
measures appropriate to the risk profile of personal data processed in connection
with the Software, including:

  **(a)** encryption of personal data in transit using TLS 1.2 or higher, where
  applicable to Network-Connected Mode operations;
  **(b)** access controls limiting access to personal data to personnel or systems
  with a legitimate operational need;
  **(c)** logging of administrative access to systems containing personal data;
  **(d)** regular security assessments and vulnerability management procedures;
  and
  **(e)** procedures for detecting, investigating, and notifying relevant parties
  of personal data breaches as required by applicable law.

**9.2 Incident Notification.**  
In the event of a personal data breach that is likely to result in a risk to the
rights and freedoms of natural persons, the Licensor shall:

  **(a)** notify affected Contributing Parties without undue delay and, where
  required by applicable law, within the legally prescribed notification window
  (72 hours under GDPR; promptly under APPI);
  **(b)** provide information sufficient for the Contributing Party to assess the
  breach and fulfill its own notification obligations; and
  **(c)** cooperate with the Contributing Party and relevant supervisory
  authorities as required.

---

### ARTICLE X — CONTACT AND REVISION

**10.1 Contact.**  
Questions, requests, or concerns regarding this Notice or the Licensor's personal
data processing practices should be directed to the Licensor through the contact
mechanism identified in the Software's documentation or the applicable service
agreement.

**10.2 Updates to This Notice.**  
This Notice may be updated from time to time. Material changes will be
communicated to Contributing Parties through the Software or through other
reasonable means. Continued use of the Software following the effective date of
a revised Notice constitutes acceptance of the revised Notice with respect to
data processed after that date.

**10.3 Supervisory Authority.**  
Data Subjects located in Japan may address concerns to the Personal Information
Protection Commission (個人情報保護委員会). Data Subjects located in the
EU/EEA may address concerns to the supervisory authority in their member state
of habitual residence, place of work, or place of an alleged infringement.
Data Subjects in other jurisdictions may contact the relevant national data
protection authority.

---

*This Notice is a repository-level baseline document. It should be supplemented
with jurisdiction-specific annexes, data processing agreements, and consent
instruments appropriate to each Organization's deployment context before any
production use involving personal data of identifiable athletes or users.*
