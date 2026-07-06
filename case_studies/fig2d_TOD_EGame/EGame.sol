// SPDX-License-Identifier: MIT

pragma solidity ^0.5.0;
contract EGame {
address payable private winner ;
uint startTime ;

constructor () public {
winner = msg.sender ;
startTime = block.timestamp ;}

function play (bytes32 guess) public {
if (keccak256(abi.encode(guess))==keccak256
(abi.encode('solution'))){
if (startTime + (5 * 1 days )==block.timestamp) {
winner = msg.sender;}}}

function getReward () payable public {
winner.transfer(msg.value);} }