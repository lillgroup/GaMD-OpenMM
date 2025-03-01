from simtk.openmm.app import *
from simtk.openmm import *
from simtk.unit import *
from sys import stdout
from sys import exit
import os
import sys
import time
import traceback
from gamd.langevin.total_boost_integrators import LowerBoundIntegrator
# from gamd.langevin.total_boost_integrators import UpperBoundIntegrator
# from gamd.langevin.dihedral_boost_integrators import import LowerBountIntegrator
# from gamd.langevin.dihedral_boost_integrators import import UpperBoundIntegrator
from gamd.stage_integrator import BoostType
from gamd.GamdLogger import GamdLogger
from gamd import utils as utils
import pprint
from gamd.langevin.total_boost_integrators import LowerBoundIntegrator as TotalBoostLowerBoundIntegrator
from gamd.langevin.total_boost_integrators import UpperBoundIntegrator as TotalBoostUpperBoundIntegrator
from gamd.langevin.dihedral_boost_integrators import LowerBoundIntegrator as DihedralBoostLowerBoundIntegrator
from gamd.langevin.dihedral_boost_integrators import UpperBoundIntegrator as DihedralBoostUpperBoundIntegrator


#
#   NOTE:  Don't do this.  It moves the forces into separate groups, so that they don't get handled properly.
#
#    for i, force in enumerate(system.getForces()):
#        print(str(i) + "     " + force.__class__.__name__)
#        force.setForceGroup(i)
#        if force.__class__.__name__ == 'PeriodicTorsionForce':
#            group = i


def set_dihedral_group(system):
    group = 1
    for force in system.getForces():
        if force.__class__.__name__ == 'PeriodicTorsionForce':
            force.setForceGroup(group)
            break
    return group


def create_lower_total_boost_integrator(system):
    return [set_dihedral_group(system), TotalBoostLowerBoundIntegrator()]


def create_upper_total_boost_integrator(system):
    return [set_dihedral_group(system), TotalBoostUpperBoundIntegrator()]


def create_lower_dihedral_boost_integrator(system):
    group = set_dihedral_group(system)
    return [group, DihedralBoostLowerBoundIntegrator(group)]


def create_upper_dihedral_boost_integrator(system):
    group = set_dihedral_group(system)
    return [group, DihedralBoostUpperBoundIntegrator(group)]


def create_output_directories(directories):
    for dir in directories:
        os.makedirs(dir, 0o755)


def main():
    starttime = time.time()
    if len(sys.argv) == 1:
        output_directory = "output"
    else:
        output_directory = sys.argv[1]

    coordinates_file = './data/md-4ns.rst7'
    prmtop_file = './data/dip.top'
    
    restarting = False
    restart_checkpoint_frequency = 1000
    restart_checkpoint_filename = "gamd.backup"
    
    if not restarting:
        create_output_directories([output_directory, output_directory + "/states/", output_directory + "/positions/",
                               output_directory + "/pdb/", output_directory + "/checkpoints"])

    # dihedral_boost = True
    
    
    
    # (simulation, integrator) = createGamdSimulationFromAmberFiles(prmtop_file, coordinates_file, dihedral_boost=dihedral_boost)

    prmtop = AmberPrmtopFile(prmtop_file)
    inpcrd = AmberInpcrdFile(coordinates_file)
    system = prmtop.createSystem(nonbondedMethod=PME, nonbondedCutoff=0.8*nanometer, constraints=HBonds)

    # [group, integrator] = create_lower_total_boost_integrator(system)
    [group, integrator] = create_upper_total_boost_integrator(system)
    # [group, integrator] = create_lower_dihedral_boost_integrator(system)
    # [group, integraotor] = create_upper_dihedral_boost_integrator(system)

    number_of_steps_in_group = 1000

    simulation = Simulation(prmtop.topology, system, integrator)
    if restarting:
        simulation.loadCheckpoint(restart_checkpoint_filename)
        write_mode = "a"
        start_step = int(integrator.getGlobalVariableByName("stepCount") // number_of_steps_in_group)
        print("restarting from saved checkpoint:", restart_checkpoint_filename,
              "at step:", start_step)
    else:
        simulation.context.setPositions(inpcrd.positions)
        if inpcrd.boxVectors is not None:
            simulation.context.setPeriodicBoxVectors(*inpcrd.boxVectors)
        simulation.minimizeEnergy()
        simulation.context.setVelocitiesToTemperature(298.15*kelvin)
        simulation.saveState(output_directory + "/states/initial-state.xml")
        simulation.reporters.append(DCDReporter(output_directory + '/output.dcd', number_of_steps_in_group))
        simulation.reporters.append(
            utils.ExpandedStateDataReporter(system, output_directory + '/state-data.log', number_of_steps_in_group, step=True,
                                            brokenOutForceEnergies=True, temperature=True,  potentialEnergy=True,
                                            totalEnergy=True, volume=True))
        print("startup time:", time.time() - starttime)
        write_mode = "w"
        start_step = 1

    gamd_logger = GamdLogger(output_directory + "/gamd.log", write_mode, integrator, simulation)

    if not restarting:
        gamd_logger.write_header()
    print("Running " + str(integrator.get_total_simulation_steps()) + " steps")
    for step in range(start_step, (integrator.get_total_simulation_steps() // number_of_steps_in_group) + 1):
        if step % restart_checkpoint_frequency // number_of_steps_in_group == 0:
            simulation.saveCheckpoint(restart_checkpoint_filename)

        # TEST
        #            if step == 250 and not restarting:
        #                print("sudden, unexpected interruption!")
        #                exit()
        # END TEST

        gamd_logger.mark_energies(group)
        try:
            # print(integrator.get_current_state())

            #
            #  NOTE:  We need to save off the starting total and dihedral potential energies, since we
            #         end up modifying them by updating the state of the particles.  This allows us to write
            #         out the values as they were at the beginning of the step for what all of the calculations
            #         for boosting were based on.
            #

            simulation.step(number_of_steps_in_group)
            gamd_logger.write_to_gamd_log(step*number_of_steps_in_group)

            # print(integrator.get_current_state())
        except Exception as e:
            print("Failure on step " + str(step * number_of_steps_in_group))
            print(e)
            # print(integrator.get_current_state())
            gamd_logger.write_to_gamd_log(step)
            sys.exit(2)

        # simulation.loadCheckpoint('/tmp/testcheckpoint')

        # debug_information = integrator.get_debugging_information()
        # getGlobalVariableNames(integrator)

        if step % integrator.ntave == 0:
            # if step % 1 == 0:

            simulation.saveState(output_directory + "/states/" + str(step * number_of_steps_in_group) + ".xml")
            simulation.saveCheckpoint(output_directory + "/checkpoints/" + str(step * number_of_steps_in_group) + ".bin")
            positions_filename = output_directory + '/positions/coordinates-' + str(step * number_of_steps_in_group) + '.csv'
            integrator.create_positions_file(positions_filename)
            # pp = pprint.PrettyPrinter(indent=2)
            # pp.pprint(debug_information)


if __name__ == "__main__":
    main()
