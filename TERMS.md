# Hymetry OSS Terms

**Effective date:** 20 January 2026

These OSS terms apply to the self-hosted, open source edition of Hymetry (the **“Software”**).  
They do **not** apply to any hosted Hymetry service (if offered), which may be governed by separate terms.

By downloading, installing, running, or modifying the Software, you agree to these terms.

---

# 1. Definitions

- **“Software”** means the Hymetry open source codebase and related artifacts obtained from an official repository or distribution, **excluding any files identified as third-party assets or separately licensed assets** (such as images, icons, fonts, illustrations, and brand materials), which remain governed by their own license terms.

- **“Operator” / “You”** means the person or entity that installs, runs, or makes the Software available to others (including as a service).

- **“End users”** means people whose interactions may be recorded or processed by the Software when the Operator deploys it.

- **“Customer data”** means recordings, events, metadata, configurations, and any other data processed or stored by the Operator’s deployment.

---

# 2. Open source license (AGPL)

## 2.1 License grant

The Software is licensed under the **GNU Affero General Public License, version 3 (or later)** (**AGPLv3+**). Your rights to use, study, modify, and share the Software are governed by the AGPL license text included with the Software distribution.

## 2.2 No additional restrictions intended

Nothing in these terms is intended to restrict rights granted to you under the AGPL. If there is a conflict, the AGPL governs to the extent of that conflict.

## 2.3 Network use / “source offer” reminder

If you modify the Software and make it available for users to interact with over a network (for example, running it as a web app for others), the AGPL may require that those users be able to obtain the corresponding source code of your modified version (for example via a visible **“Source”** link in the UI or an equivalent method).

## 2.4 Alternative licensing

The Software (or parts of it) may also be offered by the copyright holder under **other licenses** (for example, a commercial license). If you receive the Software under a separate written license agreement, that agreement may govern your use under that separate license.

---

# 3. Third-party software and licenses (including rrweb)

## 3.1 Third-party components

The Software may depend on, bundle, or integrate with third-party open source components. Those components are licensed by their respective authors under their own license terms.

## 3.2 rrweb

Hymetry uses **rrweb** as a core session recording/replay component. rrweb is distributed under the **MIT License**. You must comply with the rrweb license when using, distributing, or bundling rrweb with your deployment.

## 3.3 License precedence

Third-party components included in the Software remain subject to their respective licenses. If a third-party license grants additional rights or imposes obligations that differ from these OSS terms, **the third-party license will govern that component**.

## 3.4 Notices

Where practicable, third-party attributions and license texts should be kept in the repository and/or distributed with the Software (for example in `NOTICE`, `THIRD_PARTY_NOTICES`, or similar files).

---

# 4. Self-hosting: you are fully responsible

The OSS Software is provided for **self-hosting**. You are solely responsible for everything related to your deployment, including:

- provisioning infrastructure, hosting, and networking;
- configuration (including masking/suppression rules, retention, and access controls);
- security, monitoring, backups, incident response, and updates;
- compliance with all applicable laws, regulations, and third-party terms;
- how you collect, store, use, share, and delete Customer data.

The authors and contributors do **not** operate your deployment, do **not** control your configuration, and do **not** assume responsibility for your operational decisions.

---

# 5. Privacy and data protection responsibilities (operator-controlled)

Hymetry is a session recording / replay and analytics tool. Depending on how you configure it, the Software may capture or process information that can be personal data (for example page content, form inputs, identifiers, URLs, device/browser metadata, and interaction events).

## 5.1 You decide what is collected

As the Operator, you decide whether and how to deploy the Software, what it records, where it is stored, who can access it, and how long it is retained.

## 5.2 You are the controller (or equivalent)

For deployments that record or process end-user personal data, you are responsible for determining your legal role (controller/processor or equivalents) and meeting all related obligations.

## 5.3 Compliance with privacy laws

You must ensure that your deployment and use of the Software complies with all applicable **privacy, data protection, and electronic communications laws** in the jurisdictions where you operate or where your end users are located.

## 5.4 Notices and consent

You are responsible for providing legally compliant notices and obtaining any required consents (including for cookies/session replay) before recording end users, and for honoring opt-outs and applicable privacy rights requests.

## 5.5 Data minimization and masking

You are responsible for configuring masking/suppression and excluding pages/fields as needed to avoid recording sensitive data.

## 5.6 Do not record prohibited or sensitive data

Unless you have a verified lawful basis and have implemented strict safeguards required by law, you should not intentionally collect:

- payment card or PCI data;
- passwords, authentication secrets, or recovery codes;
- government identification numbers;
- special-category or sensitive personal data (for example health/PHI, biometric identifiers, sexual orientation, political or religious beliefs, trade-union membership);
- children’s personal data without all legally required protections and verifiable parental consent where applicable.

## 5.7 Cross-border transfers

If your deployment transfers personal data across borders, you are responsible for ensuring appropriate transfer mechanisms are in place.

---

# 6. No support; no service commitments

The Software is provided without any obligation to provide support, maintenance, uptime guarantees, security fixes, or continued availability of any feature. Any support that is provided is at the sole discretion of the maintainers.

---

# 7. Disclaimer of warranties

TO THE MAXIMUM EXTENT PERMITTED BY LAW, THE SOFTWARE IS PROVIDED **“AS IS”** AND **“AS AVAILABLE”**, WITHOUT WARRANTIES OF ANY KIND, WHETHER EXPRESS, IMPLIED, OR STATUTORY, INCLUDING WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, AND THAT THE SOFTWARE WILL BE UNINTERRUPTED, ERROR-FREE, OR SECURE.

You acknowledge that session recording and masking effectiveness depends on configuration and environment and cannot be guaranteed in all circumstances.

---

# 8. Limitation of liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW:

- THE AUTHORS, COPYRIGHT HOLDERS, AND CONTRIBUTORS WILL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, CONSEQUENTIAL, SPECIAL, EXEMPLARY, OR PUNITIVE DAMAGES, OR FOR LOST PROFITS, LOST REVENUE, LOST GOODWILL, OR LOST OR DAMAGED DATA, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.

- THE TOTAL AGGREGATE LIABILITY OF THE AUTHORS, COPYRIGHT HOLDERS, AND CONTRIBUTORS FOR ALL CLAIMS RELATING TO THE SOFTWARE WILL NOT EXCEED **USD $0**.

Some jurisdictions do not allow certain limitations, so some of the above may not apply to you.

---

# 9. Indemnification

You agree to indemnify, defend, and hold harmless the authors, copyright holders, and contributors from and against any claims, damages, losses, liabilities, and expenses (including reasonable legal fees) arising from or related to:

- your deployment or use of the Software;
- Customer data and any recordings you collect or process;
- your failure to provide notices or obtain required consents;
- your violation of law, regulation, or third-party rights; or
- your breach of third-party license terms (including rrweb’s license).

---

# 10. Trademarks

“Hymetry” and associated logos or marks may be trademarks of the project owner. The AGPL license does **not** grant trademark rights.

You may use the name only to refer to the Software in a **nominative way** and must not imply endorsement or affiliation unless you have written permission.

If you distribute a modified version of the Software or operate a public service based on it, you must **not** use the “Hymetry” name or branding in a way that suggests your version is the official Hymetry project or is endorsed by the project owners.

---

# 11. Changes to these terms

These OSS terms may be updated by publishing a new version with a new effective date. Your continued use of the Software after an update means you accept the updated terms.

---

# 12. Contact

For licensing inquiries or project contact, use the contact method listed in the official repository or website.
