import numpy as np
import pandas as pd
from pyseir import load_data


class ParameterEnsembleGenerator:
    """
    Generate ensembles of parameters for SEIR modeling.

    Parameters
    ----------
    fips: str
        County fips code.
    N_samples: int
        Integer number of samples to generate.
    t_list: array-like
        Array of times to integrate against.
    I_initial: int
        Initial infected case count to consider.
    suppression_policy: callable(t): pyseir.model.suppression_policy
        Suppression policy to apply.
    """
    def __init__(self, fips, N_samples, t_list,
                 I_initial=1, suppression_policy=None):

        self.fips = fips
        self.N_samples = N_samples
        self.I_initial = I_initial
        self.suppression_policy = suppression_policy
        self.t_list = t_list
        county_metadata = load_data.load_county_metadata()
        hospital_bed_data = load_data.load_hospital_data()

        # TODO: Some counties do not have hospitals. Likely need to go to HRR level..
        hospital_bed_data = hospital_bed_data[
            ['fips',
             'num_licensed_beds',
             'num_staffed_beds',
             'num_icu_beds',
             'bed_utilization',
             'potential_increase_in_bed_capac']].groupby('fips').sum()
        self.county_metadata_merged = county_metadata.merge(
            hospital_bed_data,  on='fips', how='left').set_index('fips').loc[fips].to_dict()

    def sample_seir_parameters(self, override_params=None):
        """
        Generate N_samples of parameter values from the priors listed below.

        Parameters
        ----------
        override_params: dict()
            Individual parameters can be overridden here.

        Returns
        -------
        : list(dict)
            List of parameter sets to feed to the simulations.
        """
        override_params = override_params or dict()
        parameter_sets = []
        for _ in range(self.N_samples):

            # https://www.cdc.gov/coronavirus/2019-ncov/hcp/clinical-guidance-management-patients.html
            # TODO: 10% is being used by CA group.  CDC suggests 20%, but this seems high.
            # Note that this is 10% of symptomatic cases, making overall hospitalization around 5%.
            hospitalization_rate_general = np.random.normal(loc=.10, scale=0.03)
            fraction_asymptomatic = np.random.uniform(0.4, 0.6)

            parameter_sets.append(dict(
                t_list=self.t_list,
                N=self.county_metadata_merged['total_population'],
                A_initial=fraction_asymptomatic * self.I_initial / (1 - fraction_asymptomatic), # assume no asymptomatic cases are tested.
                I_initial=self.I_initial,
                R_initial=0,
                E_initial=0,
                D_initial=0,
                HGen_initial=0,
                HICU_initial=0,
                HICUVent_initial=0,
                suppression_policy=self.suppression_policy,
                R0=np.random.uniform(low=3, high=4.5),            # Imperial College
                hospitalization_rate_general=hospitalization_rate_general,
                # https://www.cdc.gov/coronavirus/2019-ncov/hcp/clinical-guidance-management-patients.html
                hospitalization_rate_icu=max(np.random.normal(loc=.29, scale=0.03) * hospitalization_rate_general, 0),
                # http://www.healthdata.org/sites/default/files/files/research_articles/2020/covid_paper_MEDRXIV-2020-043752v1-Murray.pdf
                fraction_icu_requiring_ventilator=max(np.random.normal(loc=0.54, scale=0.2), 0),
                sigma=1 / np.random.normal(loc=5.1, scale=0.86),  # Imperial college
                delta=1 / np.random.gamma(5.0, scale=1),  # Kind of based on imperial college + CDC digest.
                kappa=1,
                gamma=fraction_asymptomatic,
                # https://www.cdc.gov/coronavirus/2019-ncov/hcp/clinical-guidance-management-patients.html
                symptoms_to_hospital_days=np.random.normal(loc=6.5, scale=1.5),
                symptoms_to_mortality_days=np.random.normal(loc=18.8, scale=.45), # Imperial College
                hospitalization_length_of_stay_general=np.random.normal(loc=7, scale=2),
                hospitalization_length_of_stay_icu=np.random.normal(loc=16, scale=3),
                hospitalization_length_of_stay_icu_and_ventilator=np.random.normal(loc=17, scale=3),
                mortality_rate=np.random.normal(loc=0.01, scale=0.0025),
                # if you assume the ARDS population is the group that would die
                # w/o ventilation, this would suggest a 20-42% mortality rate
                # among general hospitalized patients w/o access to ventilators:
                # “Among all patients, a range of 3% to 17% developed ARDS
                # compared to a range of 20% to 42% for hospitalized patients
                # and 67% to 85% for patients admitted to the ICU.1,4-6,8,11”

                # 10% Of the population should die at saturation levels. CFR
                # from Italy is 11.9% right now, Spain 8.9%.  System has to
                # produce,
                mortality_rate_no_general_beds=np.random.uniform(low=0.2, high=0.3),
                # Bumped these up a bit. Dyspnea -> ARDS -> Septic Shock all
                # very fatal.
                mortality_rate_no_ICU_beds=np.random.uniform(low=0.8, high=1),
                mortality_rate_no_ventilator=1,
                beds_general=  self.county_metadata_merged.get('num_licensed_beds', 0)
                             - self.county_metadata_merged.get('bed_utilization', 0)
                             + self.county_metadata_merged.get('potential_increase_in_bed_capac', 0),
                beds_ICU=self.county_metadata_merged.get('num_icu_beds', 0),

                # Rubinson L, Vaughn F, Nelson S, et al. Mechanical ventilators
                # in US acute care hospitals. Disaster Med Public Health Prep.
                # 2010;4(3):199-206. http://dx.doi.org/10.1001/dmp.2010.18.
                # 0.7 ventilators per ICU bed on average in US ~80k Assume
                # another 20-40% of 100k old ventilators can be used. = 100-120
                # for 100k ICU beds
                # TODO: Update this if possible by county or state. The ref above has state estimates
                # Staff expertise may be a limiting factor:
                # https://sccm.org/getattachment/About-SCCM/Media-Relations/Final-Covid19-Press-Release.pdf?lang=en-US
                ventilators=self.county_metadata_merged.get('num_icu_beds', 0) * np.random.uniform(low=1.0, high=1.2)
            ))

        for parameter_set in parameter_sets:
            parameter_set.update(override_params)

        return parameter_sets

    def get_average_seir_parameters(self):
        """
        Sample from the ensemble to obtain the average parameter values.

        Returns
        -------
        average_parameters: dict
            Average of the parameter ensemble, determined by sampling.
        """
        df = pd.DataFrame(self.sample_seir_parameters()).drop('t_list', axis=1)
        average_parameters = df.mean().to_dict()
        average_parameters['t_list'] = self.t_list
        return average_parameters
