# ShuttleScope Data Contribution and Grant Terms
## Version 1.0 — Effective upon first use of the Software by any Contributor

---

### PREAMBLE

These Data Contribution and Grant Terms ("Terms") govern the intellectual
property rights, data licensing obligations, permitted use authorizations, and
associated representations and warranties that arise in connection with the
submission, generation, derivation, or transmission of non-video data through
ShuttleScope or any associated service, interface, API, synchronization
mechanism, or data pipeline, whether such transmission occurs locally, over a
network, or through any other medium now known or hereafter devised.

These Terms supplement, and are incorporated by reference into, the ShuttleScope
Proprietary Source-Available License ("Software License"). In the event of a
conflict between these Terms and the Software License solely with respect to data
rights, ownership allocation, and derivative-work licensing as applied to
Contributed Data (as defined herein), these Terms control.

By installing, configuring, operating, or permitting the operation of the
Software in any environment in which Contributed Data is created or may be
created, the Contributing Party (as defined herein) accepts these Terms in full,
unconditionally, and without reservation. Acceptance is not contingent on
affirmative assent or electronic signature; continued use constitutes acceptance.

---

### ARTICLE I — DEFINITIONS

As used throughout these Terms, the following terms shall have the meanings
ascribed to them in this Article I, unless the context clearly requires a
different interpretation. Definitions are non-exhaustive with respect to scope
and shall be construed broadly in favor of the Licensor where ambiguity exists.

**1.1 "Licensor"** means the individual or legal entity holding copyright in the
Software, as identified in the Software License, including such entity's
successors, assigns, affiliated entities, and authorized representatives acting
on behalf of such entity in connection with the Software or any data processed
thereby.

**1.2 "Contributing Party"** or **"Contributor"** means any individual, team,
organization, federation, club, association, institution, or other legal or
natural person that (a) installs, deploys, or operates the Software; (b)
generates, enters, approves, synchronizes, exports, or otherwise causes the
creation of Contributed Data within or through the Software; or (c) permits,
authorizes, directs, or facilitates any of the foregoing on behalf of a third
party. For the avoidance of doubt, where the Contributing Party is an entity,
acceptance by any officer, employee, contractor, or authorized user acting within
the scope of their authority binds the entity as a whole.

**1.3 "Contributed Data"** means, in the aggregate and individually, any and all
data, records, content, information, representations, structures, and digital
artifacts of any kind that are (a) directly entered, uploaded, or submitted by a
Contributor; (b) automatically generated or captured by the Software in response
to Contributor inputs; or (c) derived, computed, transformed, inferred, or
produced by any function of the Software operating on data described in clauses
(a) or (b), in each case irrespective of the format, encoding, schema, storage
location, or medium in which such data exists or is transmitted. Contributed Data
expressly includes, without limitation, each of the following categories as they
are further defined below:

  **(a) Annotation Data** (Section 1.4);
  **(b) Match and Tournament Metadata** (Section 1.5);
  **(c) Athlete and Personnel Data** (Section 1.6);
  **(d) Derived Features and Computed Metrics** (Section 1.7);
  **(e) Aggregated and Statistical Outputs** (Section 1.8); and
  **(f) Operational and Telemetry Data** (Section 1.9).

Contributed Data expressly and unconditionally **excludes** raw match video
files and audiovisual recordings submitted or stored by Contributors in their
original, unprocessed, or minimally processed form, which are addressed
separately in the applicable service configuration documentation and customer
agreements, if any. For the avoidance of doubt, per-frame coordinate data,
timestamps extracted from video for annotation synchronization purposes, and
similar derivative records created by the Software operating on video are
Contributed Data and are not excluded by this carve-out.

**1.4 "Annotation Data"** means all structured records created or approved by a
Contributor in connection with the identification, classification, labeling,
scoring, or characterization of events occurring within a badminton match or
training session, including without limitation: rally records; point-by-point
scoring sequences; stroke-level records comprising shot type classifications,
stroke sequence numbers, player identifiers, court zone indicators (using any
zone schema including nine-zone, sixteen-zone, or continuous coordinate systems),
backhand/forehand indicators, net-relative positional flags, body-position
coordinates, opponent-position coordinates, impact coordinates, landing
coordinates, above-net flags, and timestamp offsets; end-of-rally classifications
including but not limited to ace, forced error, unforced error, net error, out,
winner, and unreachable designations; serve/receive role assignments; deuce
flags; walkover and unfinished match designations; annotation status fields;
annotation progress indicators; reviewer identifications; and any future
annotation fields added to the Software's schema.

**1.5 "Match and Tournament Metadata"** means all structured records describing
the contextual and administrative attributes of a match or competitive event,
including without limitation: tournament name and edition; tournament level or
tier classification (including any tiered nomenclature such as "IC," "IS," "SJL,"
national-level, and other designations used within the Software); tournament
grade; round designation; match date; venue; match format (singles, women's
doubles, mixed doubles, or any other format); final score representations; video
source references (including local file paths or remote URLs, but not the
underlying video content itself); video quality and camera-angle metadata;
annotator identifiers; and any notes or free-text fields associated with match
records.

**1.6 "Athlete and Personnel Data"** means all data relating to identified or
identifiable natural persons who appear in or are referenced by the Software,
including without limitation: athlete names in any language or romanization;
team or club affiliations; nationality; date of birth or birth year; world ranking
data and ranking histories; dominant hand designation; height; weight; any
physical, physiological, or biometric data to the extent recorded; performance
history associated with identified persons; user account identifiers, usernames,
roles, and credentials; and any other information that, alone or in combination
with other data fields, permits or facilitates the identification of a specific
natural person. The special treatment applicable to Athlete and Personnel Data is
set forth in Article VI and in the applicable Privacy Notice (`PRIVACY.md`).

**1.7 "Derived Features and Computed Metrics"** means all numerical, categorical,
or structured data items produced by any analytical, statistical, machine-
learning, or algorithmic function of the Software operating on Annotation Data,
Match and Tournament Metadata, or Athlete and Personnel Data, including without
limitation: per-rally expected possession value (EPV) estimates; shot influence
scores; rally-phase win rate estimates; Markov chain transition probability
matrices and related state vectors; Bayesian posterior estimates; court zone
frequency distributions; heatmap intensity values; first-return zone preference
scores; pre-loss stroke pattern rankings; post-long-rally performance differentials;
pressure-situation performance coefficients; player type classification outputs
(e.g., "short-rally specialist," "balanced," "long-rally specialist"); temporal
performance phase vectors (early-game, mid-game, late-game segments); and any
other intermediate or final numerical representations produced by an analytical
pipeline operating on Contributed Data.

**1.8 "Aggregated and Statistical Outputs"** means any report, summary, dataset,
visualization, export, or representation produced by aggregating, averaging,
ranking, clustering, sampling, or otherwise summarizing data across multiple
rallies, matches, tournaments, time periods, athletes, or organizations, including
without limitation: win rates by shot type, tournament level, match result, date
range, or any other filter dimension; rally-length distribution statistics;
service-side win rate statistics; set-comparison performance tables; opponent
vulnerability profiles; and any other output capable of being produced by the
analysis functions of the Software, whether or not those outputs are formally
identified within the Software's current feature set.

**1.9 "Operational and Telemetry Data"** means all records, logs, diagnostic
outputs, error traces, usage metrics, performance counters, configuration states,
session metadata, API call records, and other system-generated data produced by
the Software, its runtime environment, or any connected service during the
operation of the Software.

**1.10 "Data Grant"** means the license described in Article II of these Terms.

**1.11 "Network-Connected Mode"** means any mode of operation of the Software in
which Contributed Data is transmitted to, stored on, synchronized with, or made
accessible by any server, cloud service, API endpoint, relay service, or
infrastructure component that is not entirely under the exclusive local control of
the Contributing Party, including any future functionality implementing cloud
synchronization, shared workspaces, remote model training, remote analytics,
collaborative annotation, API-based data access, or similar features.

**1.12 "Model Training"** means any use of data — including Contributed Data —
to train, fine-tune, adapt, distill, calibrate, validate, benchmark, or otherwise
improve the parameters, weights, embeddings, decision rules, or outputs of any
machine learning model, statistical model, predictive algorithm, recommendation
system, reinforcement learning agent, large language model, or other automated
system, whether or not such system is deployed within the Software.

---

### ARTICLE II — DATA GRANT

**2.1 Grant of Rights.**  
Subject to the terms and conditions of these Terms, each Contributing Party
hereby irrevocably grants to the Licensor and its successors and assigns a
perpetual, worldwide, royalty-free, fully paid-up, non-exclusive (with the right
to make exclusive sub-grants as provided in Section 2.3), irrevocable (except as
expressly provided in Section 2.6), sublicensable, and transferable license
under all intellectual property rights, database rights, sui generis database
rights (including rights arising under Directive 96/9/EC of the European
Parliament or any national implementing legislation), compilation rights, trade
secret rights, and any other proprietary rights held or controlled by the
Contributing Party with respect to Contributed Data, to:

  **(a)** access, copy, store, transmit, reproduce, display, and archive
  Contributed Data, in whole or in part, in any format, encoding, or medium,
  including formats not yet existing at the time of contribution;

  **(b)** modify, adapt, transform, translate, reformat, restructure, normalize,
  de-duplicate, cleanse, label, re-label, augment, enhance, and otherwise prepare
  derivative works of Contributed Data, alone or in combination with other data;

  **(c)** use Contributed Data for **research** purposes, including fundamental
  sports science research, biomechanical research, performance science research,
  tactical and strategic analysis research, and any other academic or applied
  research regardless of the subject matter or field of inquiry;

  **(d)** use Contributed Data for **analytics** purposes, including the
  generation of statistics, performance benchmarks, aggregated profiles,
  comparative analyses, trend identifications, and any other form of systematic
  examination or reporting using Contributed Data;

  **(e)** use Contributed Data for **Model Training** purposes as defined in
  Section 1.12, including the training of any current or future models
  incorporated into or associated with the Software or related products,
  regardless of the architecture, scale, or deployment environment of such
  models;

  **(f)** use Contributed Data for **product development and improvement**
  purposes, including using Contributed Data to evaluate, validate, benchmark,
  improve, extend, or replace any feature, function, model, algorithm, user
  interface, or output of the Software or any successor or related product;

  **(g)** use Contributed Data for **commercial purposes**, including without
  limitation commercializing analytical products, analytical services, model
  outputs, platform features, research findings, benchmark datasets, and any
  other work product that incorporates or is derived from Contributed Data; and

  **(h)** exercise all of the foregoing rights through subcontractors, service
  providers, collaborators, research partners, and other third parties acting on
  behalf of the Licensor, subject to confidentiality and data handling obligations
  appropriate to the nature of the data.

**2.2 Scope of Grant with Respect to Athlete and Personnel Data.**  
The Data Grant in Section 2.1 extends to Athlete and Personnel Data as defined
in Section 1.6, subject to the privacy protections, access controls, and
processing conditions set forth in Article VI and in `PRIVACY.md`. The grant of
rights with respect to Athlete and Personnel Data does not override applicable
data protection law, and the Licensor acknowledges its obligations as a data
processor or controller (as applicable) under relevant legal frameworks. The
grant is intended to authorize, to the maximum extent permitted by applicable
law, the analytical, statistical, and research uses described in Section 2.1 as
applied to performance data associated with identified or identifiable athletes.

**2.3 Right to Sublicense.**  
The Licensor may sublicense the Data Grant, in whole or in part, to:

  **(a)** third-party research institutions, academic partners, sports
  federations, and commercial entities for any purpose consistent with these
  Terms;

  **(b)** cloud infrastructure providers, hosting providers, data processing
  vendors, model training platforms, and other service providers engaged by the
  Licensor to operate, maintain, improve, or extend the Software or related
  services; and

  **(c)** successors, acquirers, and assigns in connection with any merger,
  acquisition, asset sale, reorganization, or financing transaction.

Any sublicense granted pursuant to this Section 2.3 shall be subject to
confidentiality obligations and data handling requirements at least as protective
as those imposed on the Licensor under these Terms with respect to Athlete and
Personnel Data.

**2.4 No Restriction on Use of Outputs.**  
For the avoidance of doubt, the Licensor may independently own all intellectual
property rights in and to any outputs, reports, models, weights, summaries,
visualizations, or other works produced using Contributed Data in the exercise of
rights under the Data Grant, and no Contributing Party shall have any claim of
right, title, interest, compensation, attribution, or credit in or to such
outputs solely by virtue of having contributed underlying Contributed Data.

**2.5 Scope of Exclusion — Video Files.**  
Notwithstanding anything to the contrary in these Terms, the Data Grant does not
extend to the actual content of original match video recordings in their
unprocessed audiovisual form. The parties acknowledge that (a) video files may be
governed by separate broadcaster rights, federation rights, or third-party
agreements; (b) the Software is designed to operate on annotation layers rather
than on video content; and (c) timestamp references, frame indices, and similar
metadata within Contributed Data that reference positions within video files are
Contributed Data and are included within the Data Grant, notwithstanding that
such references may implicitly identify portions of excluded video files.

**2.6 Irrevocability; Exception.**  
The Data Grant is irrevocable except that the Licensor shall, upon written
request by a Contributing Party, cease further active use of Athlete and
Personnel Data that is demonstrably subject to a lawful data subject deletion or
restriction request under applicable data protection law, provided that:
(a) the Licensor's obligations shall not apply retroactively to Derived Features
and Aggregated and Statistical Outputs that have already been incorporated into
trained model weights, published research, or aggregated benchmarks in a manner
that does not permit practical de-aggregation; and (b) the Contributing Party
remains responsible for demonstrating the legal basis and scope of any such
deletion request.

---

### ARTICLE III — CONTRIBUTOR REPRESENTATIONS AND WARRANTIES

**3.1 Authority.**  
Each Contributing Party represents and warrants, as of the date of each
contribution and on a continuing basis throughout the period during which
Contributed Data is processed under these Terms, that:

  **(a)** it has the full right, power, and authority to enter into these Terms
  and to grant the Data Grant without the consent or approval of any third party
  that has not already been obtained;

  **(b)** the collection, creation, storage, processing, and transmission of
  Athlete and Personnel Data through the Software is conducted in compliance with
  all applicable data protection laws, athlete welfare regulations, employment
  laws, collective bargaining agreements, federation rules, and privacy policies
  to which the Contributing Party or the relevant athletes are subject;

  **(c)** where Athlete and Personnel Data includes data relating to professional
  or amateur athletes, the Contributing Party has obtained all legally required
  consents, authorizations, or other legal bases for the processing contemplated
  by these Terms, including for the transfer of such data to the Licensor; and

  **(d)** the submission of Contributed Data does not infringe, misappropriate, or
  violate any third-party intellectual property right, contractual right, privacy
  right, personality right, right of publicity, or any other right recognized
  under any applicable legal system.

**3.2 Accuracy.**  
Contributing Parties are solely responsible for the accuracy, completeness,
integrity, and quality of Contributed Data. The Licensor makes no representation
that Contributed Data will be validated, corrected, or audited prior to use under
the Data Grant.

---

### ARTICLE IV — NETWORK-CONNECTED MODE

**4.1 Current Status.**  
As of the effective date of Version 1.0 of these Terms, the Software operates
primarily in a local, offline mode in which Contributed Data is stored on devices
under the Contributing Party's direct control. The provisions of this Article IV
are prospective and establish the terms that will govern any future introduction
of Network-Connected Mode features, whether by the Licensor through a software
update, optional module, or hosted service offering.

**4.2 Activation of Network-Connected Mode.**  
In the event that the Software is updated to include Network-Connected Mode
features, or in the event that the Contributing Party elects to use any network-
based feature that causes Contributed Data to be transmitted to infrastructure
not under the Contributing Party's exclusive local control:

  **(a)** the Data Grant set forth in Article II shall automatically extend to
  all Contributed Data transmitted in connection with such Network-Connected Mode
  feature, without any additional consent or act by the Contributing Party, it
  being understood that acceptance of these Terms at the time of initial Software
  use constitutes advance consent to such extension;

  **(b)** the Licensor shall implement and maintain reasonable technical and
  organizational measures to protect Contributed Data in transit and at rest in
  accordance with industry-standard practices applicable to sports performance
  data;

  **(c)** Contributed Data transmitted in Network-Connected Mode may be stored,
  processed, and analyzed on servers located in any jurisdiction in which the
  Licensor or its subprocessors maintain infrastructure, and the Contributing
  Party acknowledges and consents to such cross-border processing to the extent
  not prohibited by applicable law;

  **(d)** the Licensor may use Contributed Data received via Network-Connected
  Mode for Model Training purposes, including centralized and federated training
  approaches, in accordance with the Data Grant;

  **(e)** the Licensor shall provide Contributing Parties with reasonable advance
  notice prior to the introduction of any Network-Connected Mode feature that
  materially alters the categories of Contributed Data transmitted or the primary
  purposes for which such data is used, provided that failure to provide such
  notice shall not void the Data Grant or limit the Licensor's rights under these
  Terms;

  **(f)** Contributing Parties operating in jurisdictions subject to regulatory
  requirements governing cross-border data transfers (including without
  limitation the European Economic Area, United Kingdom, Japan, and South Korea)
  remain responsible for determining whether additional contractual mechanisms —
  such as standard contractual clauses, binding corporate rules, or equivalent
  instruments — are required for their own compliance, and the Licensor shall
  cooperate reasonably with such requirements upon request; and

  **(g)** the Licensor may implement API rate limiting, access controls, data
  quotas, and similar technical measures in connection with Network-Connected Mode
  services, and such measures shall not constitute a breach of these Terms or of
  the Software License.

**4.3 Offline Mode Preservation.**  
Nothing in these Terms obligates the Contributing Party to use Network-Connected
Mode features. Contributing Parties that elect to operate exclusively in offline
mode are subject to the Data Grant solely with respect to Contributed Data
processed on locally controlled devices, and the network-transmission provisions
of Section 4.2 do not apply until such time as Network-Connected Mode is enabled.

---

### ARTICLE V — OWNERSHIP, COMPILATIONS, AND DERIVATIVE WORKS

**5.1 Compilation Rights.**  
The Licensor shall be the sole owner of any compilation, dataset, benchmark,
corpus, or aggregate work created by the Licensor from Contributed Data received
from multiple Contributing Parties, provided that such ownership is in the
compilation as a whole and does not affect the Contributing Party's retained
rights in its own individual contributions as set forth in Section 5.2.

**5.2 Retained Rights.**  
Subject to the Data Grant, each Contributing Party retains all ownership rights
it holds in Contributed Data as submitted. The grant of the Data Grant does not
constitute a transfer of ownership of Contributed Data to the Licensor. The
Contributing Party retains the right to use its own Contributed Data for any
purpose not inconsistent with these Terms.

**5.3 No Obligation to Use.**  
The Licensor is under no obligation to use any Contributed Data, to retain any
Contributed Data for any particular duration, or to exercise any of the rights
granted under the Data Grant.

---

### ARTICLE VI — ATHLETE AND PERSONAL DATA

**6.1 Acknowledgment of Special Category.**  
The parties acknowledge that Athlete and Personnel Data as defined in Section 1.6
includes information relating to identified or identifiable natural persons and
may therefore constitute personal data, personal information, or equivalent
categories of protected data under applicable privacy and data protection laws,
including without limitation the Act on the Protection of Personal Information
(Japan, Act No. 57 of 2003, as amended), the General Data Protection Regulation
(EU) 2016/679, the UK GDPR, and equivalent legislation in other relevant
jurisdictions.

**6.2 Processing Roles.**  
As between the Contributing Party and the Licensor:

  **(a)** where the Contributing Party deploys the Software in a purely local,
  offline environment, the Contributing Party acts as the sole data controller or
  equivalent responsible party, and the Licensor's access to Athlete and Personnel
  Data is limited to the development, maintenance, and support of the Software
  codebase itself, without direct access to the Contributing Party's data;

  **(b)** where the Contributing Party uses Network-Connected Mode features that
  result in Athlete and Personnel Data being transmitted to the Licensor's
  infrastructure, the Licensor acts as a data processor with respect to the
  Contributing Party (as data controller) for the purpose of service delivery,
  and simultaneously as an independent data controller with respect to its own
  use of such data under the Data Grant for analytical, research, and development
  purposes to the extent authorized by applicable law and the Contributing Party's
  representations in Article III.

**6.3 Minimum Protection Standards.**  
With respect to Athlete and Personnel Data received by the Licensor, the Licensor
shall:

  **(a)** implement and maintain technical and organizational measures appropriate
  to the sensitivity of sports performance data relating to identified individuals,
  including measures designed to prevent unauthorized disclosure of individual
  performance profiles to competitors, third-party commercial data brokers, or
  other parties whose access would foreseeably harm the interests of the athletes
  concerned;

  **(b)** not publish or publicly disclose Athlete and Personnel Data in a form
  that identifies specific individual athletes by name in combination with their
  performance weaknesses, injury indicators, or tactical vulnerabilities, unless
  the Contributing Party has expressly authorized such publication or the relevant
  individual has provided informed consent;

  **(c)** use Athlete and Personnel Data for Model Training purposes in ways that
  produce model weights and outputs, rather than in ways that directly republish
  the underlying personal data records; and

  **(d)** upon written request from a Contributing Party identifying a lawful
  data subject request received from an athlete whose data is held by the
  Licensor, respond to such request in accordance with applicable law and the
  provisions of `PRIVACY.md`.

**6.4 Contributing Party Obligations.**  
The Contributing Party acknowledges that:

  **(a)** the Software is designed for use by sports organizations and analysts in
  connection with athletes whose performance data is legitimately within the
  organization's operational scope;

  **(b)** where athletes have not been informed that their performance data will
  be processed using third-party software tools and shared with the software
  developer, the Contributing Party is solely responsible for providing such
  information and obtaining any required consents before using the Software in
  connection with such athletes' data;

  **(c)** the Contributing Party shall not submit to the Software any Athlete and
  Personnel Data in respect of which the Contributing Party lacks a lawful basis
  for processing under applicable data protection law;

  **(d)** special categories of data relating to athletes — including health data,
  biometric data, and data capable of revealing physical or medical conditions —
  should not be submitted unless the Contributing Party has independently
  determined that a lawful basis exists for such submission and for the data
  grant described in Article II; and

  **(e)** the Data Grant does not, by itself, constitute a legal basis for
  processing under applicable data protection law; the Contributing Party remains
  responsible for establishing and maintaining an independent legal basis.

---

### ARTICLE VII — TERM, SURVIVAL, AND AMENDMENT

**7.1 Term.**  
These Terms take effect upon the Contributing Party's first use of the Software
and continue in effect until all Contributed Data submitted under these Terms has
been permanently deleted from all systems under the Licensor's control, provided
that rights granted under Article II that have been exercised prior to deletion —
including rights in Derived Features, Aggregated Outputs, and trained model
weights — survive deletion and remain in full force and effect.

**7.2 Effect of Software License Termination.**  
Termination of the Software License does not terminate the Data Grant. The Data
Grant with respect to Contributed Data already submitted survives any termination
of the Software License.

**7.3 Amendment.**  
The Licensor may publish updated versions of these Terms. Use of the Software
following the publication of an updated version constitutes acceptance of the
updated Terms with respect to Contributed Data submitted or generated after the
effective date of such update. Previously submitted Contributed Data remains
subject to the Terms in effect at the time of original submission, except that
the Contributing Party may affirmatively accept updated Terms in their entirety.

---

### ARTICLE VIII — GOVERNING PROVISIONS

**8.1 Integration.**  
These Terms, together with the Software License, `PRIVACY.md`, and any
applicable service agreement, constitute the entire agreement between the parties
with respect to the subject matter hereof and supersede all prior negotiations,
representations, warranties, and understandings relating thereto.

**8.2 Severability.**  
If any provision of these Terms is held to be invalid, illegal, or unenforceable
under applicable law, such provision shall be modified to the minimum extent
necessary to make it enforceable, or if modification is not possible, shall be
severed, in each case without affecting the validity or enforceability of the
remaining provisions.

**8.3 No Waiver.**  
No failure or delay by the Licensor in exercising any right under these Terms
shall operate as a waiver of such right. No single or partial exercise of any
right shall preclude any other or further exercise thereof or the exercise of any
other right.

**8.4 Assignment.**  
The Licensor may assign these Terms and all rights and obligations hereunder,
in whole or in part, without notice to or consent of the Contributing Party.
The Contributing Party may not assign these Terms or any obligations hereunder
without the prior written consent of the Licensor.

**8.5 Language.**  
The authoritative version of these Terms is the English-language version. Any
translations provided for informational purposes do not constitute legal
instruments and shall not be relied upon to interpret or override the English
text.
