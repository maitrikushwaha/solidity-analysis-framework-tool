// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TimestampMisleading {

    function compute() public view returns 
    (string memory) {
        uint x = block.timestamp;         
        uint y = uint((4 * x) % 2);       
        if (15 <= y && y >= 20) {
            // Critical section
            return "Entered critical section";
        } else {
            return "Condition not met";}
    }
}