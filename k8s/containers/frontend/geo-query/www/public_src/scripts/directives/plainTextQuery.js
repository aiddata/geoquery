angular.module('aiddataDET')
.directive('plainTextQuery', function($window) {
  return {
    restrict: 'E',
    scope: {
      dataset: '=queryDataset',
      geography: '=queryGeography',
      filters: '=queryFilters',
      options: '=queryOptions',
      editable: '=queryEditable'
    },
    controller: 'PlainTextQueryCtrl',
    templateUrl: "views/components/plainTextQuery.html"
  };
});
