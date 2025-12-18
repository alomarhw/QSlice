
include "stdgates.inc";


gate hadamard_cnot a, b {
    h a;
    h b;
    cx a, b;
    h a;
    h b;
}

qubit[5] p;

hadamard_cnot p[0], p[1];

hadamard_cnot p[3], p[4];
