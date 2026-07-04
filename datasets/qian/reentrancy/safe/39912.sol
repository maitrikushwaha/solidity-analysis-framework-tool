pragma solidity ^0.4.25;


contract CampaignBeneficiary{

    address public Resilience;

    function simulatePathwayFromBeneficiary() public payable {
        bytes4 buySig = bytes4(sha3("buy()"));
        if (!Resilience.call.value(msg.value)(buySig)) throw;
    }
}