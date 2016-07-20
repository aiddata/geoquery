angular.module('aiddataDET')
.controller('QueryTextCtrl', function($scope, $rootScope, $log, $state, $stateParams, queryFactory) {
  $scope.filters = queryFactory.filters;
  $scope.options = queryFactory.options;
  $scope.searchData = $state.params.dataset ? { dataset: $state.params.dataset } : {};
  $scope.dataset = {};
  $scope.totals = {};
  $scope.queryStructure = {};
  $scope.geography = $stateParams.boundary;
  $scope.requestData = { name: 'New Request', editing: false };

  $scope.removeFilter = function(filter, option) {
    return $scope.dataset.type === 'release' ? queryFactory.toggleFilterOff(filter, option) :
      queryFactory.toggleOptionOff(filter, option);
  };

  $scope.clearFilters = function () {
    _.chain($scope.queryStructure)
      .filter(function(param) {
        return param.optional && param.value && param.value.length;
      })
      .each(function(param) {
        return $scope.dataset.type === 'release' ? queryFactory.resetFilter(param.key) :
          queryFactory.resetOption(param.key);
      })
      .value();
  };

  $rootScope.$on('filters:update', function(e, data) {
    $scope.searchData = data;
  });

  $rootScope.$on('filters:updated', function(e, data) {
    $scope.totals = _.pick(data, ['projects', 'locations']);

    // Being Redefined with each filters:updated event because it directly
    // references $scope vars which will need to be update
    $scope.queryStructure = setQueryStructure();
  });

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;
    $scope.queryStructure = setQueryStructure();
  });

  function setQueryStructure () {
    return [
      { value: [ $scope.dataset.title ], pre: 'Extract data from ', optional: false },
      { value: [ $scope.geography ], pre: 'within ', optional: false },
      { value: $scope.searchData.donors, pre: 'given by ', optional: true, key: 'donors' },
      { value: $scope.searchData.ad_sector_names, pre: 'to promote ', optional: true, key: 'ad_sector_names' },
      { value: $scope.options.options.extract_types, pre: 'calculating', optional: true, key: 'options.extract_types' },
      { value: $scope.options.files, pre: 'using', optional: true, key: 'files' }
    ];
  }


  function init () {
    queryFactory.setBoundary($stateParams.boundary, $stateParams.subboundary);
  }
  init();
});
