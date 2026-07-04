/*
 * @source: https://github.com/sigp/solidity-security-blog
 * @author: -
 * @vulnerable_at_lines: 18,20
 */

pragma solidity ^0.4.25;

contract Roulette {
    uint public pastBlockTime; // Forces one bet per block

    constructor() public payable {} // initially fund contract

    // fallback function used to make a bet
    function () public payable {
        require(msg.value == 10 ether); // must send 10 ether to play
        // <yes> <report> TIME_MANIPULATION
        require(now != pastBlockTime); // only 1 transaction per block  [TIMESTAMP-DEPENDENT, line 18: 'now' gates the one-bet-per-block check]
        // <yes> <report> TIME_MANIPULATION
        pastBlockTime = now;  // [TIMESTAMP-DEPENDENT, line 20] 'now' stored as pastBlockTime
        if(now % 15 == 0) { // winner  [TIMESTAMP-DEPENDENT, line 21: 'now % 15' decides the winner, miner-manipulable]
            msg.sender.transfer(this.balance);
        }
    }
}
