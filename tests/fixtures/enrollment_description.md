HCP can complete the PEF online via the portal or manually via fax. CM360 will transcribe the PEF into the CRM, and then CM360 will send PEF confirmation of fax back to the HCP.
Enrollment record is then created in CM360
Then CM360 checks if the diagnosis code on the PEF is off-label. They can also learn that it is off-label via an HCP inbound call.
Off-label process
If it is off-label, CM360 will check if the patient is 18 or older, and if the diagnosis code is equal to the ones in their document. If that is true, the PSM will contact the prescribing officer and confirm the diagnosis code selected. Otherwise, they are off-label.
They will then see if the HCP indicates that they believe the patient has an on-label condition that just hasn’t been confirmed through genetic testing. If that is the case, the PSM can reactively tell the prescriber to select the on-label diagnosis code, and that free post-rx genetic testing is offered to confirm the diagnosis after the patient starts treatment.
If the prescriber agrees, the patient will proceed with enrollment. If the free test disproved the on-label diagnosis, the PSM will contact the HCP and see if the doctor insists on their clinical judgement that the patient does have the on-label diagnosis. If they do, the patient will continue as normal. If they don’t the patient is officially off-label
If the patient is deemed off-label, they either won’t be entered into the CRM or just archived. CM360 will send the Off-label notification fax to the HCP office, and the HCP will have to work directly with the SP biologics.
From there, duplicate patient check will happen. If the patient exists already, CM360 system will determine whether this is a re-enrollment, restart, or an update to an existing care plan.
Duplicate handlingprocess
If it is a new patient, CM 360 will create the patient record and associate it with the correct care plan. Then, they will create the BI case with the status being ‘PENDING’ and the substatus being ‘NEW PATIENT – HUB ENROLLED’.
This status is sent to QRAL, and QRAL sends it to JCRM
This status automatically creates the onboarding case. The PSM is assigned via zip to territory mapping.
Next we check if there is missing info. If there is (sections 1, 2, 5, or 6), the ‘Collect MI’ task is automatically created.
CM360 Missing Info Process
CM360 does their own missing info check that includes written consent
CM360 will send the missing information fax to the HCP as many times as needed, and they will also notify the PSM via teams. They will also upload fax communication to the CRM.
CM360 will then send any missing information to the CRM through QRAL, including written consent
PSM Missing Info Process
From there, the PSM will notify the Hemolytic Anemia Specialist. They will continually outreach to the HCP until all required information via the missing info list in Salesforce is obtained. If the HAS is blocked because they can’t access PHI, the PSM will step in to help. If it’s been 6 weeks with the inability to contact the patient and collect required information, than enrollment will be cancelled.
If patient consent is part of what is missing, the PSM will attempt to contact the patient. They will call every other business day for a total of 3 attempts, and will also try reaching out using alternate channels at their discretion.
If the patient isn’t responsive, the PSM will try contacting the HCP. They'll verify patient contact details, inform the office they haven't been unable to move forward, and request the office help in contacting the patient by providing theirr own contact information
If the HCP isn’t responsive, the PSM will eventually contact the HAS (at their discretion time wise) via teams or email or call to report the status and request alternate contacts for the HCP. They will not share any PHI with the HAS They will also send a non-responsive letter to the patient containing a hard copy of patient consent, as well as an email that uses the no-consent email template.
If its been 2 weeks with the inability to contact the HCP and collect the required information, then enrollment will be cancelled.
As part of cancellation, the PSM will alert their manager with the reasoning being an unresponsive patient. Once the manager approves, the PSM will notify the HCP and HAS that the PEF is being cancelled, and alert CM360 who will update the patient status in the CRM
If the patient is responsive, consent can be retrieved
If written through Docusign, PSM must send a link via text or email and document this in the CRM.
If written through paper copy. PSM must mail a paper copy of the consent form to the patient or caregiver, and document this in the CRM.
If verbal, the patient cannot be a California resident, and written consent must be collected within 30 days. PSM should update the consent record in the CRM and note verbal consent was collected
Once everything is obtained, on CM360’s end, they will send patient data and the activated coverage determination milestone to QRAL, who will send this to PSCRM.
This triggers the creation of the benefits investigation case, which creates the tasks Confirm Benefits Details task and Additional Info needed to complete BI automatically
Once everything is obtained on PSCRM’s end,the ‘Collect MI’ task will be manually closed by the agent. That triggers the ‘Make Welcome Call’ and ‘Send Welcome Materials’ tasks to be created and manually closed by the PSM.
and a careplan is created with onboarding and coverage determination milestones activated on CM360 system
