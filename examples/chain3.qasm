include "stdgates.inc";

qubit q1;
qubit q2;
qubit q3;

h q1;
h q2;

cx q1, q2;
cx q2, q3;

bit bit1;
bit bit2;
bit bit3;

bit1 = measure q1;
bit2 = measure q2;
bit3 = measure q3;
