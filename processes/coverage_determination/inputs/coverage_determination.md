Coverage Determination
As soon as CM360 sends patient data and milestone to QRAL, Biologics will start the BI process.
Once PSCRM receives it, the benefits investigation case will be automatically created, which creates the tasks Confirm Benefits Details task and Additional Info needed to complete BI automatically
If at any point additional info is needed, the PSM will gather the information required. In either case, they will manually close the additional info task
If the patient’s active member plan becomes inactive, the BI Completed - Plan Termed task will be automatically created and the PSM will reach out to the patient and discuss the insurance change/coverage status before manually closing the task.
We don’t know exactly when or how the trigger will work yet, but Biologics will perform any logic required and send benefits details to QRAL, who will send them to PSCRM, with the BV Case Substatus they send being ‘BENEFITS INVESTIGATION – COMPLETE'.
If the patient is not covered or uninsured, the active member plan is deactivated and the patient is marked as uninsured. The PSM will notice this and begin the PAP process.
If the patient is covered or covered with restrictions, they check if they have commercial insurance. If they do, the patient is enrolled into copay. If they aren’t, then the workflow continues
In either case, after copay eligibility Biologics will then evaluate if PA is required. If it is, then the PA Case Substatus sent will be ‘PRIOR AUTHORIZATION INITIATION’. If not, then that will be ‘PA not required’
Once this is received by PSCRM a few things will happen in parallel
It closes the Confirm Benefits details task automatically. This opens the ‘Communicate Benefits’ task that will be manually closed by the PSM after they reach out to the patient. If there is no copay enrollment, the benefits investigation case is closed automatically from the last case being closed.
If insurance type is commercial, the Copay Enrollment task will be created. This will be closed when Biologics finishes copay enrollment and sends back the Copay Case Substatus = ‘COPAY CARD ENROLLMENT’. This closes the Copay enrollment task and then closes the benefits investigation case because the last task is closed
The PA case will be created automatically.
If PA is needed, the PA Needed task will be created automatically.
If PA is not needed, the PA Not Needed task will be created automatically.
This will create the Communicate PA Not Needed to Patient and HCP tasks, which are manually closed by the PSM when they contact both
This automatically closes the PA case, and we move onto the Shipment process
In the meantime, Biologics is going through the process of PA if it’s required. It then will send the PA case status to QRAL, which will go to PSCRM
If the PA substatus is approved, the Communicate PA Approval To Patient and HCP tasks are created. The PSM will manually close these tasks after updating the patient and HCP, which closes the PA case automatically.
If the patient is Med-Part D, the PSM will also try to speak to them regarding affordability. If they can’t afford to be on the medicine, then the PAP process will begin. Otherwise, shipment process will begin.
If the PA substatus is denied, the Communicate PA Denial to Patient and HCP tasks will be created. They will then manually close these tasks, which will close the PA case automatically.
In the meantime, Biologics is going through the appeal process. They will then send an appeal case substatus to QRAL, which will then be sent to PSCRM
If the appeal case substatus is not ‘Appeal available’, then the PAP process will start
Otherwise, the Appeal Case is created and then we wait for the Appeal Case Status to be sent from Biologics through QRAL
If the appeal is approved, the Communicate Appeal Approval to Patient and HCP tasks will be created, and the PSM will manually close these are contacting the patient and HCP. This automatically closes the Appeal case
If the patient is Med-Part D, the PSM will also try to speak to them regarding affordability. If they can’t afford to be on the medicine, then the PAP process will begin. Otherwise, shipment process will begin.
If the appeal is denied, the Communicate Appeal Denial to Patient and HCP tasks will be created. The PSM will manually contact both and close both tasks. If it’s possible for another appeal to be put in, this will retry. Otherwise, the appeal case will then automatically close, and the PAP process will begin.
